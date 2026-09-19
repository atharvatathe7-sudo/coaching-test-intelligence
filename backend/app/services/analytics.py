from sqlalchemy.orm import Session

from ..database.models import (
    Chapter,
    Question,
    Student,
    StudentAnswer,
    Test,
    Topic,
)


def analyze_questions(db: Session, test_id: int) -> list[dict]:
    """
    Analyze every question in a test.
    """

    test = db.get(Test, test_id)

    if test is None:
        raise ValueError(f"Test {test_id} not found.")

    questions = (
        db.query(Question)
        .filter(Question.test_id == test_id)
        .order_by(Question.question_number)
        .all()
    )

    if not questions:
        raise ValueError(f"Test {test_id} has no questions.")

    analysis = []

    for question in questions:
        answers = (
            db.query(StudentAnswer)
            .filter(
                StudentAnswer.test_id == test_id,
                StudentAnswer.question_id == question.id,
            )
            .all()
        )

        correct_count = 0
        wrong_count = 0
        blank_count = 0

        for student_answer in answers:
            answer = student_answer.answer

            if answer is None or answer.strip() == "":
                blank_count += 1

            elif (
                answer.strip().upper()
                == question.correct_answer.strip().upper()
            ):
                correct_count += 1

            else:
                wrong_count += 1

        total_responses = (
            correct_count
            + wrong_count
            + blank_count
        )

        if total_responses > 0:
            correct_percentage = (
                correct_count / total_responses
            ) * 100

            wrong_percentage = (
                wrong_count / total_responses
            ) * 100

            blank_percentage = (
                blank_count / total_responses
            ) * 100
        else:
            correct_percentage = 0.0
            wrong_percentage = 0.0
            blank_percentage = 0.0

        analysis.append(
            {
                "question_id": question.id,
                "question_number": question.question_number,
                "subject": question.subject,
                "chapter_id": question.chapter_id,
                "topic_id": question.topic_id,
                "correct_answer": question.correct_answer,
                "difficulty": question.difficulty,
                "correct_count": correct_count,
                "wrong_count": wrong_count,
                "blank_count": blank_count,
                "total_responses": total_responses,
                "correct_percentage": round(
                    correct_percentage, 2
                ),
                "wrong_percentage": round(
                    wrong_percentage, 2
                ),
                "blank_percentage": round(
                    blank_percentage, 2
                ),
            }
        )

    return analysis


def analyze_topics_and_chapters(
    db: Session,
    test_id: int,
) -> dict:
    """
    Aggregate question performance into topic-level
    and chapter-level analytics.
    """

    question_analysis = analyze_questions(db, test_id)

    chapters = {
        chapter.id: chapter
        for chapter in db.query(Chapter).all()
    }

    topics = {
        topic.id: topic
        for topic in db.query(Topic).all()
    }

    topic_stats = {}
    chapter_stats = {}

    for question in question_analysis:

        topic_id = question["topic_id"]
        chapter_id = question["chapter_id"]

        if topic_id not in topic_stats:
            topic_stats[topic_id] = {
                "topic_id": topic_id,
                "topic_name": topics[topic_id].name,
                "chapter_id": chapter_id,
                "chapter_name": chapters[chapter_id].name,
                "questions": 0,
                "correct": 0,
                "wrong": 0,
                "blank": 0,
                "responses": 0,
            }

        topic_stats[topic_id]["questions"] += 1
        topic_stats[topic_id]["correct"] += question["correct_count"]
        topic_stats[topic_id]["wrong"] += question["wrong_count"]
        topic_stats[topic_id]["blank"] += question["blank_count"]
        topic_stats[topic_id]["responses"] += question["total_responses"]

        if chapter_id not in chapter_stats:
            chapter_stats[chapter_id] = {
                "chapter_id": chapter_id,
                "chapter_name": chapters[chapter_id].name,
                "subject": chapters[chapter_id].subject,
                "questions": 0,
                "correct": 0,
                "wrong": 0,
                "blank": 0,
                "responses": 0,
            }

        chapter_stats[chapter_id]["questions"] += 1
        chapter_stats[chapter_id]["correct"] += question["correct_count"]
        chapter_stats[chapter_id]["wrong"] += question["wrong_count"]
        chapter_stats[chapter_id]["blank"] += question["blank_count"]
        chapter_stats[chapter_id]["responses"] += question["total_responses"]

    for stats in topic_stats.values():

        if stats["responses"] > 0:
            stats["correct_percentage"] = round(
                stats["correct"]
                / stats["responses"]
                * 100,
                2,
            )

            stats["wrong_percentage"] = round(
                stats["wrong"]
                / stats["responses"]
                * 100,
                2,
            )

            stats["blank_percentage"] = round(
                stats["blank"]
                / stats["responses"]
                * 100,
                2,
            )

        else:
            stats["correct_percentage"] = 0.0
            stats["wrong_percentage"] = 0.0
            stats["blank_percentage"] = 0.0

    for stats in chapter_stats.values():

        if stats["responses"] > 0:
            stats["correct_percentage"] = round(
                stats["correct"]
                / stats["responses"]
                * 100,
                2,
            )

            stats["wrong_percentage"] = round(
                stats["wrong"]
                / stats["responses"]
                * 100,
                2,
            )

            stats["blank_percentage"] = round(
                stats["blank"]
                / stats["responses"]
                * 100,
                2,
            )

        else:
            stats["correct_percentage"] = 0.0
            stats["wrong_percentage"] = 0.0
            stats["blank_percentage"] = 0.0

    topics_result = sorted(
        topic_stats.values(),
        key=lambda item: item["correct_percentage"],
    )

    chapters_result = sorted(
        chapter_stats.values(),
        key=lambda item: item["correct_percentage"],
    )

    return {
        "test_id": test_id,
        "topics": topics_result,
        "chapters": chapters_result,
    }


def analyze_students(
    db: Session,
    test_id: int,
) -> list[dict]:
    """
    Generate an individual diagnostic profile for every student
    who participated in a test.
    """

    test = db.get(Test, test_id)

    if test is None:
        raise ValueError(f"Test {test_id} not found.")

    questions = (
        db.query(Question)
        .filter(Question.test_id == test_id)
        .order_by(Question.question_number)
        .all()
    )

    if not questions:
        raise ValueError(f"Test {test_id} has no questions.")

    students = (
        db.query(Student)
        .join(
            StudentAnswer,
            StudentAnswer.student_id == Student.id,
        )
        .filter(StudentAnswer.test_id == test_id)
        .distinct()
        .order_by(Student.roll_number)
        .all()
    )

    if not students:
        raise ValueError(
            f"Test {test_id} has no student answers."
        )

    chapters = {
        chapter.id: chapter
        for chapter in db.query(Chapter).all()
    }

    topics = {
        topic.id: topic
        for topic in db.query(Topic).all()
    }

    results = []

    for student in students:

        answers = (
            db.query(StudentAnswer)
            .filter(
                StudentAnswer.test_id == test_id,
                StudentAnswer.student_id == student.id,
            )
            .all()
        )

        answer_map = {
            answer.question_id: answer
            for answer in answers
        }

        correct_count = 0
        wrong_count = 0
        blank_count = 0

        chapter_stats = {}
        topic_stats = {}
        difficulty_stats = {}

        for question in questions:

            student_answer = answer_map.get(question.id)

            if student_answer is None:
                answer = None
            else:
                answer = student_answer.answer

            if answer is None or answer.strip() == "":
                response_type = "blank"
                blank_count += 1

            elif (
                answer.strip().upper()
                == question.correct_answer.strip().upper()
            ):
                response_type = "correct"
                correct_count += 1

            else:
                response_type = "wrong"
                wrong_count += 1

            chapter_id = question.chapter_id

            if chapter_id not in chapter_stats:
                chapter_stats[chapter_id] = {
                    "chapter_id": chapter_id,
                    "chapter_name": chapters[chapter_id].name,
                    "subject": chapters[chapter_id].subject,
                    "questions": 0,
                    "correct": 0,
                    "wrong": 0,
                    "blank": 0,
                }

            chapter_stats[chapter_id]["questions"] += 1
            chapter_stats[chapter_id][response_type] += 1

            topic_id = question.topic_id

            if topic_id not in topic_stats:
                topic_stats[topic_id] = {
                    "topic_id": topic_id,
                    "topic_name": topics[topic_id].name,
                    "chapter_id": chapter_id,
                    "chapter_name": chapters[chapter_id].name,
                    "questions": 0,
                    "correct": 0,
                    "wrong": 0,
                    "blank": 0,
                }

            topic_stats[topic_id]["questions"] += 1
            topic_stats[topic_id][response_type] += 1

            difficulty = (
                question.difficulty
                or "unknown"
            ).lower()

            if difficulty not in difficulty_stats:
                difficulty_stats[difficulty] = {
                    "difficulty": difficulty,
                    "questions": 0,
                    "correct": 0,
                    "wrong": 0,
                    "blank": 0,
                }

            difficulty_stats[difficulty]["questions"] += 1
            difficulty_stats[difficulty][response_type] += 1

        for stats in chapter_stats.values():

            attempted = (
                stats["correct"]
                + stats["wrong"]
            )

            if attempted > 0:
                stats["accuracy"] = round(
                    stats["correct"]
                    / attempted
                    * 100,
                    2,
                )
            else:
                stats["accuracy"] = 0.0

            stats["correct_percentage"] = round(
                stats["correct"]
                / stats["questions"]
                * 100,
                2,
            )

            stats["blank_percentage"] = round(
                stats["blank"]
                / stats["questions"]
                * 100,
                2,
            )

        for stats in topic_stats.values():

            attempted = (
                stats["correct"]
                + stats["wrong"]
            )

            if attempted > 0:
                stats["accuracy"] = round(
                    stats["correct"]
                    / attempted
                    * 100,
                    2,
                )
            else:
                stats["accuracy"] = 0.0

            stats["correct_percentage"] = round(
                stats["correct"]
                / stats["questions"]
                * 100,
                2,
            )

            stats["blank_percentage"] = round(
                stats["blank"]
                / stats["questions"]
                * 100,
                2,
            )

        for stats in difficulty_stats.values():

            attempted = (
                stats["correct"]
                + stats["wrong"]
            )

            if attempted > 0:
                stats["accuracy"] = round(
                    stats["correct"]
                    / attempted
                    * 100,
                    2,
                )
            else:
                stats["accuracy"] = 0.0

        chapter_list = sorted(
            chapter_stats.values(),
            key=lambda item: item["accuracy"],
        )

        topic_list = sorted(
            topic_stats.values(),
            key=lambda item: item["accuracy"],
        )

        strongest_topics = sorted(
            topic_stats.values(),
            key=lambda item: item["accuracy"],
            reverse=True,
        )[:3]

        weakest_topics = sorted(
            topic_stats.values(),
            key=lambda item: item["accuracy"],
        )[:3]

        marks = (
            correct_count * test.marks_correct
            + wrong_count * test.marks_wrong
            + blank_count * test.marks_blank
        )

        attempted = correct_count + wrong_count

        if attempted > 0:
            overall_accuracy = round(
                correct_count
                / attempted
                * 100,
                2,
            )
        else:
            overall_accuracy = 0.0

        negative_marks = (
            wrong_count
            * abs(test.marks_wrong)
        )

        results.append(
            {
                "student_id": student.id,
                "roll_number": student.roll_number,
                "student_name": student.name,
                "test_id": test_id,
                "marks": marks,
                "correct": correct_count,
                "wrong": wrong_count,
                "blank": blank_count,
                "attempted": attempted,
                "accuracy": overall_accuracy,
                "negative_marks": negative_marks,
                "chapters": chapter_list,
                "topics": topic_list,
                "strongest_topics": strongest_topics,
                "weakest_topics": weakest_topics,
                "difficulty": list(
                    difficulty_stats.values()
                ),
            }
        )

    results.sort(
        key=lambda item: item["marks"],
        reverse=True,
    )

    return results


def analyze_batch(
    db: Session,
    test_id: int,
) -> dict:
    """
    Generate batch-level intelligence for a test.

    Combines student, question, chapter, and topic analytics
    into one teacher-facing data structure.
    """

    test = db.get(Test, test_id)

    if test is None:
        raise ValueError(f"Test {test_id} not found.")

    student_results = analyze_students(db, test_id)
    question_results = analyze_questions(db, test_id)
    topic_chapter_results = analyze_topics_and_chapters(
        db,
        test_id,
    )

    if not student_results:
        raise ValueError(
            f"Test {test_id} has no student results."
        )

    # ---------------------------------
    # BATCH OVERVIEW
    # ---------------------------------

    student_count = len(student_results)

    total_marks = sum(
        student["marks"]
        for student in student_results
    )

    total_correct = sum(
        student["correct"]
        for student in student_results
    )

    total_wrong = sum(
        student["wrong"]
        for student in student_results
    )

    total_blank = sum(
        student["blank"]
        for student in student_results
    )

    total_attempted = sum(
        student["attempted"]
        for student in student_results
    )

    total_negative_marks = sum(
        student["negative_marks"]
        for student in student_results
    )

    average_marks = round(
        total_marks / student_count,
        2,
    )

    average_accuracy = round(
        sum(
            student["accuracy"]
            for student in student_results
        ) / student_count,
        2,
    )

    if total_attempted > 0:
        batch_accuracy = round(
            total_correct
            / total_attempted
            * 100,
            2,
        )
    else:
        batch_accuracy = 0.0

    # ---------------------------------
    # STUDENT DISTRIBUTION
    # ---------------------------------

    # These are descriptive score bands for reporting.
    # They are not stored as permanent student categories.

    high_performers = [
        student
        for student in student_results
        if student["accuracy"] >= 70
    ]

    middle_performers = [
        student
        for student in student_results
        if 50 <= student["accuracy"] < 70
    ]

    needs_attention = [
        student
        for student in student_results
        if student["accuracy"] < 50
    ]

    distribution = {
        "accuracy_70_plus": len(high_performers),
        "accuracy_50_to_69": len(middle_performers),
        "accuracy_below_50": len(needs_attention),
    }

    # ---------------------------------
    # QUESTION ALERTS
    # ---------------------------------

    # Questions with less than 40% batch correctness
    # are surfaced as difficult-question alerts.

    difficult_questions = [
        question
        for question in question_results
        if question["correct_percentage"] < 40
    ]

    difficult_questions = sorted(
        difficult_questions,
        key=lambda item: item["correct_percentage"],
    )

    # ---------------------------------
    # BLANK-HEAVY QUESTIONS
    # ---------------------------------

    blank_heavy_questions = [
        question
        for question in question_results
        if question["blank_percentage"] >= 20
    ]

    blank_heavy_questions = sorted(
        blank_heavy_questions,
        key=lambda item: item["blank_percentage"],
        reverse=True,
    )

    # ---------------------------------
    # HIGH-WRONG QUESTIONS
    # ---------------------------------

    high_wrong_questions = [
        question
        for question in question_results
        if question["wrong_percentage"] >= 50
    ]

    high_wrong_questions = sorted(
        high_wrong_questions,
        key=lambda item: item["wrong_percentage"],
        reverse=True,
    )

    # ---------------------------------
    # TOP / BOTTOM STUDENTS
    # ---------------------------------

    top_students = student_results[:5]
    bottom_students = student_results[-5:]

    # ---------------------------------
    # BATCH CHAPTERS / TOPICS
    # ---------------------------------

    chapters = topic_chapter_results["chapters"]
    topics = topic_chapter_results["topics"]

    # ---------------------------------
    # FINAL BATCH REPORT
    # ---------------------------------

    return {
        "test_id": test_id,
        "test_name": test.name,
        "subject": test.subject,
        "student_count": student_count,

        "overview": {
            "average_marks": average_marks,
            "highest_marks": student_results[0]["marks"],
            "lowest_marks": student_results[-1]["marks"],
            "average_accuracy": average_accuracy,
            "batch_accuracy": batch_accuracy,
            "total_correct": total_correct,
            "total_wrong": total_wrong,
            "total_blank": total_blank,
            "total_attempted": total_attempted,
            "total_negative_marks": total_negative_marks,
        },

        "student_distribution": distribution,

        "chapters": chapters,

        "topics": topics,

        "difficult_questions": difficult_questions,

        "blank_heavy_questions": blank_heavy_questions,

        "high_wrong_questions": high_wrong_questions,

        "top_students": top_students,

        "bottom_students": bottom_students,

        "students": student_results,
    }
