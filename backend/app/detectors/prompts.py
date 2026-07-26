def text_prompt(material: str) -> str:
    return (
        "Analyze whether production methods in this Bilibili video use AI-generated media. "
        "Discussion about AI as a topic is not evidence of AI production. Return concrete JSON "
        "evidence with timestamps when available. Material:\n" + material
    )


def visual_prompt(frame_count: int) -> str:
    return (
        "Inspect sampled video frames for concrete AI-generation artifacts. Distinguish depicted "
        "AI topics from AI production methods. Return strict JSON evidence with frame_index. "
        f"Frames supplied: {frame_count}."
    )
