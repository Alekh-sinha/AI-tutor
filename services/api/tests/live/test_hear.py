import array
import math

from ai_teacher_api.live import answer, hear


def tone(seconds: float, amp: int) -> bytes:
    n = int(seconds * hear.RATE)
    return array.array("h", [int(amp * math.sin(i / 7)) for i in range(n)]).tobytes()


def chunks(pcm: bytes):
    step = int(hear.RATE * hear.CHUNK_S) * 2
    return [pcm[i:i + step] for i in range(0, len(pcm), step)]


def run(u, pcm):
    return [r for c in chunks(pcm) if (r := u.feed(c))]


def test_utterance_ends_after_silence_and_keeps_the_first_word():
    u = hear.Utterance()
    out = run(u, tone(0.6, 30) + tone(1.5, 4000) + tone(2.0, 30))
    assert len(out) == 1
    assert 2.5 < len(out[0]) / 2 / hear.RATE < 3.6  # 0.5 s pre-roll + 1.5 s speech + the 1.3 s silence that ended it, not the whole 4.1 s


def test_noise_alone_is_not_an_utterance():
    assert run(hear.Utterance(), tone(5, 150)) == []


def test_a_click_is_not_an_utterance():
    u = hear.Utterance()
    assert run(u, tone(0.5, 30) + tone(0.2, 5000) + tone(2.0, 30)) == []


def test_done_button_finishes_early():
    u = hear.Utterance()
    run(u, tone(0.5, 30) + tone(1.0, 4000))
    pcm = u.finish()
    assert pcm and len(pcm) / 2 / hear.RATE >= 1.0


def test_message_never_lets_an_unclear_answer_be_praised():
    m = answer.message("रानी", "[unclear]", "क्या होता है?", None)
    assert "could not be understood" in m and "right" not in m.split("Do not")[0]
    v = {"verdict": "wrong", "reason": "it is the opposite", "teacher_should_say": "Not quite."}
    m = answer.message("रानी", "चाँद", "क्या होता है?", v)
    assert "WRONG" in m and "चाँद" in m
