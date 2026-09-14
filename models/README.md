# Models Directory

Place your local GGUF language models and Whisper speech models here.

### Recommended Directory Layout

```text
models/
├── llm/
│   └── Qwen3-8B-Q4_K_M.gguf  (or Qwen3-14B-Q4_K_M.gguf)
└── speech-to-text/
    └── whisper/
        └── ggml-large-v3-turbo-q5_0.bin
```

> **Note**: Binary model weights are excluded from Git version control due to file size limits (>100MB). Download them separately and reference them in your `.env` configuration.
