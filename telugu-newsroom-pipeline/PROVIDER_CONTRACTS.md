# Model Provider Contracts

The pipeline sends one JSON object on stdin and expects one JSON object on stdout.
Adapters may call an on-prem model, a cloud API, or an ensemble. Nonzero exit codes,
logs on stdout, and malformed JSON fail the stage. Put logs on stderr.

## Speech adapter

Input:

```json
{
  "task": "transcribe_and_diarize",
  "audio_path": "/absolute/path/audio.wav",
  "language": "te",
  "requirements": {
    "word_timestamps": true,
    "speaker_labels": true,
    "overlap_regions": true,
    "confidence": true
  }
}
```

Output:

```json
{
  "language": "te",
  "duration": 63.42,
  "provider": "provider-name",
  "model": "model-version",
  "timing_quality": "word",
  "segments": [
    {
      "id": "seg-00001",
      "start": 0.32,
      "end": 4.91,
      "speaker": "SPEAKER_01",
      "confidence": 0.94,
      "overlap_speakers": [],
      "text": "తెలుగు ట్రాన్స్క్రిప్ట్",
      "words": [
        {
          "text": "తెలుగు",
          "start": 0.32,
          "end": 0.88,
          "confidence": 0.96,
          "speaker": "SPEAKER_01",
          "timing_source": "aligned"
        }
      ]
    }
  ]
}
```

Speaker labels are anonymous until separately resolved from verified metadata.

## Editorial adapter

The input contains clips with start/end, transcript, speakers, and evidence IDs.
The adapter must use only that evidence.

Output:

```json
{
  "clips": [
    {
      "id": "clip-0001",
      "topic": "Politics & Government",
      "subtopic": "District project review",
      "title": "జిల్లాల ప్రాజెక్టులపై ముఖ్యమంత్రి సమీక్ష",
      "summary": "Evidence-grounded Telugu summary.",
      "importance": 0.86,
      "hook": 0.78,
      "self_contained": 0.91,
      "reason": "Contains the decision and its direct consequence.",
      "named_entities": ["Nara Chandrababu Naidu"]
    }
  ]
}
```

All three numeric signals must be between 0 and 1. Invalid or unknown clip IDs are
rejected or ignored rather than silently attached to another clip.

