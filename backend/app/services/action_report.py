from sqlalchemy.orm import Session

from .analytics import analyze_batch


def generate_teacher_action_report(db: Session, test_id: int) -> dict:
    """
    Convert batch analytics into a structured teacher action report.

    This function does not diagnose the cause of poor performance.
    It identifies data-supported areas that deserve teacher attention.
    """

    data = analyze_batch(db, test_id)

    priorities = []

    # 1. Difficult questions
    for question in data["difficult_questions"]:
        priorities.append(
            {
                "type": "difficult_question",
                "priority": "high",
                "title": f"Review Question {question['question_number']}",
                "reason": (
                    f"Only {question['correct_percentage']}% of students "
                    "answered this question correctly."
                ),
                "evidence": question,
                "suggested_action": (
                    "Review the question, answer key, and related concept "
                    "with the batch."
                ),
            }
        )

    # 2. Weak chapters
    for chapter in data["chapters"]:
        if chapter["correct_percentage"] < 50:
            priorities.append(
                {
                    "type": "weak_chapter",
                    "priority": "high",
                    "title": f"Review {chapter['chapter_name']}",
                    "reason": (
                        f"Batch correctness is "
                        f"{chapter['correct_percentage']}%."
                    ),
                    "evidence": chapter,
                    "suggested_action": (
                        "Review and consider reteaching the weak concepts "
                        "from this chapter."
                    ),
                }
            )

    # 3. Weak topics
    for topic in data["topics"]:
        if topic["correct_percentage"] < 45:
            priorities.append(
                {
                    "type": "weak_topic",
                    "priority": "high",
                    "title": f"Focus on {topic['topic_name']}",
                    "reason": (
                        f"Batch correctness is "
                        f"{topic['correct_percentage']}%."
                    ),
                    "evidence": topic,
                    "suggested_action": (
                        "Review this topic and inspect the questions "
                        "responsible for the weak performance."
                    ),
                }
            )

    # 4. High-wrong questions
    for question in data["high_wrong_questions"]:
        priorities.append(
            {
                "type": "high_wrong_question",
                "priority": "medium",
                "title": f"Inspect Question {question['question_number']}",
                "reason": (
                    f"{question['wrong_percentage']}% of students "
                    "answered this question incorrectly."
                ),
                "evidence": question,
                "suggested_action": (
                    "Inspect the question and common incorrect responses "
                    "before deciding whether reteaching is needed."
                ),
            }
        )

    # 5. Blank-heavy questions
    for question in data["blank_heavy_questions"]:
        priorities.append(
            {
                "type": "blank_heavy_question",
                "priority": "medium",
                "title": f"Inspect Question {question['question_number']}",
                "reason": (
                    f"{question['blank_percentage']}% of students "
                    "left this question blank."
                ),
                "evidence": question,
                "suggested_action": (
                    "Review whether the question reflects a knowledge gap, "
                    "difficulty issue, or time-management problem."
                ),
            }
        )

    # Remove duplicate focus where possible.
    seen = set()
    unique_priorities = []

    for item in priorities:
        key = (item["type"], item["title"])

        if key not in seen:
            seen.add(key)
            unique_priorities.append(item)

    return {
        "test_id": data["test_id"],
        "test_name": data["test_name"],
        "student_count": data["student_count"],
        "overview": data["overview"],
        "priorities": unique_priorities,
        "priority_count": len(unique_priorities),
    }
