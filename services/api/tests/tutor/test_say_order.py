import asyncio

from ai_teacher_api.tutor import agent as tutor


def test_parallel_says_stop_after_a_question(monkeypatch):
    async def fake_synth(*a, **k):
        await asyncio.sleep(0.01)
        return b"\0\0"

    monkeypatch.setattr("ai_teacher_api.common.tts.synth_retry", fake_synth)
    monkeypatch.setattr("ai_teacher_api.common.tts.to_mp3", lambda pcm: b"mp3")
    monkeypatch.setattr(tutor, "_tts_client", lambda: None)

    async def run():
        turn = tutor.Turn(queue=asyncio.Queue(), session_id="t")
        tutor.CURRENT.set(turn)
        # the model asks and answers in ONE response: the calls run concurrently
        res = await asyncio.gather(tutor.say("पहले यह बताओ?"), tutor.say("उत्तर यह है।"))
        return turn, res

    turn, res = asyncio.run(run())
    assert res[0]["status"] == "ok" and res[1]["status"] == "error"
    assert turn.said == 1
