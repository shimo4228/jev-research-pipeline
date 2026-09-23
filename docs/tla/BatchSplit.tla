------------------------------- MODULE BatchSplit -------------------------------
(* JevClient.judge_batch: a refused batch is split in halves, recursively.
   Items 1..N; Poison = the items whose content makes a request fail by size.
   Mode "size":   only a batch containing a poison item is refused (413 / max_tokens).
   Mode "shared": every request is refused whatever it holds (bad key, shared part).
   SplitOnShared: the old policy (split on any 4xx) vs the fixed one (size only).      *)
EXTENDS Naturals, FiniteSets

CONSTANTS N, Poison, Mode, SplitOnShared

VARIABLES pending, judged, failed, requests
vars == <<pending, judged, failed, requests>>

Range(lo, hi) == {i \in 1..N : lo <= i /\ i <= hi}
Refused(lo, hi) == IF Mode = "shared" THEN TRUE ELSE Range(lo, hi) \cap Poison # {}
Splittable == Mode = "size" \/ SplitOnShared

Init ==
  /\ pending = {<<1, N>>}
  /\ judged = {} /\ failed = {}
  /\ requests = 0

Send(b) ==
  LET lo == b[1]  hi == b[2]  mid == (lo + hi) \div 2 IN
  /\ requests' = requests + 1
  /\ IF ~Refused(lo, hi)
       THEN /\ judged' = judged \cup Range(lo, hi)
            /\ pending' = pending \ {b} /\ UNCHANGED failed
       ELSE IF lo < hi /\ Splittable
         THEN /\ pending' = (pending \ {b}) \cup {<<lo, mid>>, <<mid + 1, hi>>}
              /\ UNCHANGED <<judged, failed>>
         ELSE /\ failed' = failed \cup Range(lo, hi)
              /\ pending' = pending \ {b} /\ UNCHANGED judged

Next == (\E b \in pending : Send(b)) \/ (pending = {} /\ UNCHANGED vars)
Spec == Init /\ [][Next]_vars /\ WF_vars(Next)

Done == pending = {}
\* The bad item sinks alone: everything else gets its answer.
Isolated == Done /\ Mode = "size" => (failed = Poison /\ judged = (1..N) \ Poison)
\* Never more requests than a full binary split.
RequestsBounded == requests <= 2 * N - 1
\* A refusal every half would get is paid for once.
SharedPaidOnce == Mode = "shared" => requests <= 1
Terminates == <>Done
=============================================================================
