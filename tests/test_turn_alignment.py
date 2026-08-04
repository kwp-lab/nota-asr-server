import numpy as np

from nota_asr_server.backends.base import AlignedToken, BackendSegment, SpeakerTraceChunk
from nota_asr_server.backends.speaker_clustering import ClusterCapture
from nota_asr_server.backends.turn_alignment import (
    build_speaker_turns,
    capture_speaker_trace,
    decode_speaker_trace,
    encode_speaker_trace,
    extract_aligned_tokens,
    global_speaker_prototypes,
    refine_segments_with_turns,
)


def test_capture_reconstructs_all_camplus_chunks_and_hidden_speaker_centers():
    raw = [
        {
            "sentence_info": [
                {"start": 0, "end": 3000, "sentence": "甲乙丙", "spk": 0}
            ]
        }
    ]
    capture = ClusterCapture(
        embeddings=np.asarray(
            [[1.0, 0.0], [0.0, 1.0], [0.0, 3.0]], dtype=np.float32
        ),
        labels=np.asarray([9, 4, 4]),
    )

    trace, centers = capture_speaker_trace(raw, capture)

    assert [(chunk.start, chunk.end) for chunk in trace] == [
        (0.0, 1.5),
        (0.75, 2.25),
        (1.5, 3.0),
    ]
    assert [chunk.local_speaker for chunk in trace] == [0, 1, 1]
    assert centers == ((1.0, 0.0), (0.0, 2.0))


def test_extracts_nano_and_sensevoice_alignment_formats():
    nano = extract_aligned_tokens(
        [
            {
                "timestamps": [
                    {"token": "甲", "start_time": 0.1, "end_time": 0.2},
                    {"token": "乙", "start_time": 0.2, "end_time": 0.3},
                ]
            }
        ]
    )
    sensevoice = extract_aligned_tokens(
        [{"words": ["甲", "乙"], "timestamp": [[100, 200], [200, 300]]}]
    )

    assert nano == sensevoice
    assert [token.text for token in nano] == ["甲", "乙"]


def test_trace_blob_round_trip_uses_bounded_compact_storage():
    trace = (
        SpeakerTraceChunk(0.0, 1.5, 0, (1.0, 0.0, 0.5)),
        SpeakerTraceChunk(0.75, 2.25, 1, (0.0, 1.0, -0.5)),
    )

    payload = encode_speaker_trace(trace)
    restored = decode_speaker_trace(payload)

    assert len(payload) < 2_000
    assert [(item.start, item.end, item.local_speaker) for item in restored] == [
        (0.0, 1.5, 0),
        (0.75, 2.25, 1),
    ]
    assert np.allclose(restored[1].embedding, trace[1].embedding, atol=0.001)


def test_global_turns_split_one_vad_segment_on_exact_token_boundaries():
    trace = (
        SpeakerTraceChunk(0.0, 1.0, 0, (1.0, 0.0, 0.0)),
        SpeakerTraceChunk(1.0, 2.0, 1, (0.0, 1.0, 0.0)),
        SpeakerTraceChunk(2.0, 3.0, 2, (0.0, 0.0, 1.0)),
    )
    local_to_cluster = {(0, 0): 5, (0, 1): 8, (0, 2): 13}
    prototypes = global_speaker_prototypes(((0, trace),), local_to_cluster)
    turns = build_speaker_turns(
        trace,
        window_index=0,
        local_to_cluster=local_to_cluster,
        prototypes=prototypes,
    )
    tokens = (
        AlignedToken(0.1, 0.8, "甲"),
        AlignedToken(1.1, 1.8, "乙"),
        AlignedToken(2.1, 2.8, "丙"),
    )

    refined = refine_segments_with_turns(
        (BackendSegment(0.0, 3.0, "甲乙丙", "speaker_0"),),
        tokens,
        turns,
        window_index=0,
        local_to_cluster=local_to_cluster,
    )

    assert [(text, speaker) for _, _, text, speaker in refined] == [
        ("甲", 5),
        ("乙", 8),
        ("丙", 13),
    ]


def test_alignment_mismatch_keeps_the_original_segment_without_losing_text():
    trace = (SpeakerTraceChunk(0.0, 2.0, 0, (1.0, 0.0)),)
    mapping = {(0, 0): 2}
    turns = build_speaker_turns(
        trace,
        window_index=0,
        local_to_cluster=mapping,
        prototypes={2: (1.0, 0.0)},
    )

    refined = refine_segments_with_turns(
        (BackendSegment(0.0, 2.0, "完整文本", "speaker_0"),),
        (AlignedToken(0.1, 0.2, "不匹配"),),
        turns,
        window_index=0,
        local_to_cluster=mapping,
    )

    assert refined == ((0.0, 2.0, "完整文本", 2),)
