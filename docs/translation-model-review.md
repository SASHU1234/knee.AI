# Translation model review: ai4bharat/indictrans2-en-indic-dist-200M

- Revision pinned: `2cfd0a20057756d756bf3e53528f492afc52f91a` (reviewed 2026-11-05).
- Licence: MIT. HF access: gated "auto" (accept terms + `hf auth login`, once).
- Size: ~1.1 GB on disk (safetensors), ~1.3 GB RSS loaded (measured, CPU, fp32).
- Remote code (`configuration_indictrans.py` 309 lines, `modeling_indictrans.py` 1803,
  `tokenization_indictrans.py` 251) reviewed: imports are only torch, transformers, sentencepiece,
  stdlib `json`/`os`/`math`/`typing`. No network calls, subprocess, `eval`/`exec`, pickle, or
  environment access. File I/O is limited to reading/writing tokenizer vocab JSON/SentencePiece
  files. Loaded with `local_files_only=True` from the pinned local snapshot.
- Not chosen: IndicTrans3-beta (LLM-scale, unsuitable for CPU); the 1B en-indic model (much larger, not needed).
- Measured findings that shaped the service (synthetic text): letter placeholders were transliterated
  by the Hindi model -> digit-only placeholders; short sentences with grouping dropped "narrowing"
  in Tamil -> one sentence per segment; Tamil rendered "meniscus" as "menstrual" -> clinical terms kept
  in English; occasional runaway "......" output -> length budget + retry + rejection.
