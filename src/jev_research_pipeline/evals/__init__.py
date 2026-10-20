"""Offline evaluation of the pipeline's parts on frozen data: `jrp eval gate` for S (selection)
and X (evidence and slots), `jrp eval intake` for I (intake). Nothing here runs in `jrp run`
or `jrp wbr`; an eval reads a store and writes only under evals.paths.eval_root."""
