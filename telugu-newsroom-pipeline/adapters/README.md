# Provider adapters

`deepgram_speech.py` is a production-shaped speech adapter for Telugu. It sends
the extracted mono WAV to Nova-3 with the current batch diarizer and converts the
response into the MediaOps evidence contract.

Set `DEEPGRAM_API_KEY`, then use:

```bash
MEDIAOPS_SPEECH_COMMAND="python /app/adapters/deepgram_speech.py"
```

For higher proper-noun accuracy, benchmark a newsroom test set and maintain a
provider-side vocabulary/keyterm layer. Speaker labels remain anonymous until an
editor verifies identity. The adapter does not claim overlapping-speech regions;
add an overlap detector (for example, pyannote) before automatically clearing the
strict quality gate.
