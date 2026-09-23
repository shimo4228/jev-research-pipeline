---------------------------- MODULE StageConcurrency ----------------------------
(* One pipeline stage (pipeline/run.py LineRun._jev + StoredJev.judge + JevClient.judge).
   Every action is atomic because asyncio only switches tasks at an await; the actions are
   cut exactly at the awaits of the Python code.
   Flags choose the design:
     CheckInsideSlot  cost cap read after the semaphore slot is taken (as built) or before
     CountAtAdmit     cost counted before the request's first await (Jev, as built) or
                      only when the answer comes back (Qwen tokens)
     SingleFlight     an identical judgment already in flight is joined (as built)       *)
EXTENDS Naturals, FiniteSets

CONSTANTS N, K, Q, Cap, CheckInsideSlot, CountAtAdmit, SingleFlight

Tasks == 1..N
\* Tasks 1 and 2 ask the same judgment (the same claim accepted for two questions).
Key == [t \in Tasks |-> IF t = 2 THEN 1 ELSE t]
Keys  == {Key[t] : t \in Tasks}

VARIABLES pc, slots, cost, known, inflight, sentPerKey
vars == <<pc, slots, cost, known, inflight, sentPerKey>>

Over == cost > Cap

Init ==
  /\ pc = [t \in Tasks |-> "init"]
  /\ slots = K
  /\ cost = 0
  /\ known = {}
  /\ inflight = {}
  /\ sentPerKey = [k \in Keys |-> 0]

\* The design without CheckInsideSlot reads the cap before queueing on the semaphore.
Start(t) ==
  /\ pc[t] = "init"
  /\ IF ~CheckInsideSlot /\ Over
       THEN pc' = [pc EXCEPT ![t] = "skipped"]
       ELSE pc' = [pc EXCEPT ![t] = "wait"]
  /\ UNCHANGED <<slots, cost, known, inflight, sentPerKey>>

Acquire(t) ==
  /\ pc[t] = "wait" /\ slots > 0
  /\ slots' = slots - 1
  /\ pc' = [pc EXCEPT ![t] = "slot"]
  /\ UNCHANGED <<cost, known, inflight, sentPerKey>>

\* Inside the slot, up to the first await: cap check, store hit, join, or send.
InSlot(t) ==
  /\ pc[t] = "slot"
  /\ CASE CheckInsideSlot /\ Over ->
            /\ pc' = [pc EXCEPT ![t] = "skipped"] /\ slots' = slots + 1
            /\ UNCHANGED <<cost, known, inflight, sentPerKey>>
       [] Key[t] \in known ->
            /\ pc' = [pc EXCEPT ![t] = "done"] /\ slots' = slots + 1
            /\ UNCHANGED <<cost, known, inflight, sentPerKey>>
       [] SingleFlight /\ Key[t] \in inflight ->
            /\ pc' = [pc EXCEPT ![t] = "joined"]
            /\ UNCHANGED <<slots, cost, known, inflight, sentPerKey>>
       [] OTHER ->
            /\ pc' = [pc EXCEPT ![t] = "sent"]
            /\ inflight' = inflight \cup {Key[t]}
            /\ sentPerKey' = [sentPerKey EXCEPT ![Key[t]] = @ + 1]
            /\ cost' = IF CountAtAdmit THEN cost + Q ELSE cost
            /\ UNCHANGED <<slots, known>>

Complete(t) ==
  /\ pc[t] = "sent"
  /\ pc' = [pc EXCEPT ![t] = "done"]
  /\ slots' = slots + 1
  /\ known' = known \cup {Key[t]}
  /\ inflight' = inflight \ {Key[t]}
  /\ cost' = IF CountAtAdmit THEN cost ELSE cost + Q
  /\ UNCHANGED sentPerKey

Joined(t) ==
  /\ pc[t] = "joined" /\ Key[t] \in known
  /\ pc' = [pc EXCEPT ![t] = "done"]
  /\ slots' = slots + 1
  /\ UNCHANGED <<cost, known, inflight, sentPerKey>>

Finished == \A t \in Tasks : pc[t] \in {"done", "skipped"}

Next ==
  \/ \E t \in Tasks : Start(t) \/ Acquire(t) \/ InSlot(t) \/ Complete(t) \/ Joined(t)
  \/ (Finished /\ UNCHANGED vars)

Spec == Init /\ [][Next]_vars /\ WF_vars(Next)

\* ---- properties ---------------------------------------------------------------
InFlightBounded == Cardinality({t \in Tasks : pc[t] \in {"slot", "sent", "joined"}}) <= K
OvershootOneRequest == cost <= Cap + Q            \* Jev as built: at most one request past the cap
OvershootInFlight   == cost <= Cap + K * Q        \* at most what the slots let through
NoDuplicateRequest  == \A k \in Keys : sentPerKey[k] <= 1
AllSettle == <>Finished
=============================================================================
