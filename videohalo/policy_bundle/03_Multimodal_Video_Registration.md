# Multimodal Video Registration

VideoHALO 3.7 retains Gemini-native minimal registration while using the
Enterprise ADC and private-GCS production boundary.

## Canonical local registration

For each source video:

```text
resolve source → SHA-256 → MIME/container check → ffprobe stream census
→ short decode smoke test → canonical timeline → VideoManifest
```

The manifest preserves video, speech audio, non-speech audio, on-screen text capability, camera/editing capability, and container metadata. Registration does not semantically transcribe or interpret the media.

## Provider materialization

The original compatible file is uploaded once to a private Google Cloud
Storage bucket in the same approved project. The immutable `gs://` URI is
reused by the Taxonomy Planner, Fact Extractor, Fact Reflection, and Candidate
Reflection. Object identity is bound to the local SHA-256, object metadata,
generation, and canonical manifest. Temporary Gemini Files API uploads are not
part of the production runtime.

## Authentication and access

Gemini inference uses Application Default Credentials and IAM. API-key
environment variables are rejected by the production runtime. The runner uses
the global Enterprise endpoint and a least-privilege principal with model-use
and bucket-scoped object permissions only. GCS objects remain private and are
never converted to public HTTP URLs.

## Bounded native retry

One focused retry may narrow the time interval or raise native media resolution for a fine visual detail. If the fact remains undecidable, it is excluded from construction.

## No external semantic tools

The baseline forbids external ASR, OCR, speaker diarization, sound-event detection, object tracking, dense-frame extraction, slow motion, and contact sheets.
