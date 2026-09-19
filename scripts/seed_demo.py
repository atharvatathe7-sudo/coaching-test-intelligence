import random
import sys
from datetime import date
from pathlib import Path


# Allow importing backend.app...
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


from backend.app.database.connection import Base, SessionLocal, engine
from backend.app.database.models import (
    Batch,
    Chapter,
    Institute,
    Question,
    Student,
    StudentAnswer,
    Test,
    Topic,
)


def create_demo_data():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        # ---------------------------------------------------------
        # 1. Institute
        # ---------------------------------------------------------

        institute = Institute(
            name="ABC NEET Academy"
        )

        db.add(institute)
        db.flush()

        # ---------------------------------------------------------
        # 2. Batch
        # ---------------------------------------------------------

        batch = Batch(
            institute_id=institute.id,
            name="NEET 2027 - Physics A",
        )

        db.add(batch)
        db.flush()

        # ---------------------------------------------------------
        # 3. Students
        # ---------------------------------------------------------

        students = []

        for i in range(1, 21):
            student = Student(
                batch_id=batch.id,
                roll_number=f"PHY-{i:03d}",
                name=f"Student {i:02d}",
            )

            db.add(student)
            students.append(student)

        db.flush()

        # ---------------------------------------------------------
        # 4. Test
        # ---------------------------------------------------------

        test = Test(
            batch_id=batch.id,
            name="Physics Test 01",
            subject="Physics",
            test_date=date.today(),
            marks_correct=4,
            marks_wrong=-1,
            marks_blank=0,
        )

        db.add(test)
        db.flush()

        # ---------------------------------------------------------
        # 5. Chapters and topics
        # ---------------------------------------------------------

        chapter_topic_data = {
            "Mechanics": [
                "Kinematics",
                "Newton's Laws",
                "Friction",
                "Work Energy",
                "Rotation",
            ],
            "Thermodynamics": [
                "Temperature",
                "Heat Transfer",
            ],
            "Waves": [
                "Wave Motion",
                "Sound",
            ],
            "Optics": [
                "Ray Optics",
                "Lenses",
            ],
            "Modern Physics": [
                "Atoms",
                "Nuclei",
            ],
        }

        chapters = {}
        topics = {}

        for chapter_name, topic_names in chapter_topic_data.items():

            chapter = Chapter(
                subject="Physics",
                name=chapter_name,
            )

            db.add(chapter)
            db.flush()

            chapters[chapter_name] = chapter

            for topic_name in topic_names:

                topic = Topic(
                    chapter_id=chapter.id,
                    name=topic_name,
                )

                db.add(topic)
                db.flush()

                topics[(chapter_name, topic_name)] = topic

        # ---------------------------------------------------------
        # 6. Questions
        # ---------------------------------------------------------

        question_topics = []

        for chapter_name, topic_names in chapter_topic_data.items():
            for topic_name in topic_names:
                question_topics.append(
                    (chapter_name, topic_name)
                )

        answers = ["A", "B", "C", "D"]

        questions = []

        for question_number in range(1, 31):

            chapter_name, topic_name = question_topics[
                (question_number - 1) % len(question_topics)
            ]

            question = Question(
                test_id=test.id,
                question_number=question_number,
                subject="Physics",
                chapter_id=chapters[chapter_name].id,
                topic_id=topics[
                    (chapter_name, topic_name)
                ].id,
                correct_answer=random.choice(answers),
                difficulty=random.choice(
                    ["easy", "medium", "hard"]
                ),
            )

            db.add(question)
            questions.append(question)

        db.flush()

        # ---------------------------------------------------------
        # 7. Student answers
        # ---------------------------------------------------------

        for student in students:

            for question in questions:

                # Roughly:
                # 70% chance of attempting correctly/wrongly
                # 10% blank
                roll = random.random()

                if roll < 0.10:
                    answer = None

                elif roll < 0.75:
                    # Sometimes correct, sometimes wrong.
                    if random.random() < 0.75:
                        answer = question.correct_answer
                    else:
                        wrong_answers = [
                            x for x in answers
                            if x != question.correct_answer
                        ]
                        answer = random.choice(wrong_answers)

                else:
                    wrong_answers = [
                        x for x in answers
                        if x != question.correct_answer
                    ]
                    answer = random.choice(wrong_answers)

                student_answer = StudentAnswer(
                    test_id=test.id,
                    student_id=student.id,
                    question_id=question.id,
                    answer=answer,
                )

                db.add(student_answer)

        db.commit()

        print()
        print("Demo dataset created successfully.")
        print("-----------------------------------")
        print(f"Institute: {institute.name}")
        print(f"Batch:     {batch.name}")
        print(f"Students:  {len(students)}")
        print(f"Test:      {test.name}")
        print(f"Questions: {len(questions)}")
        print("-----------------------------------")
        print("Database:", engine.url.database)
        print()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    create_demo_data()
