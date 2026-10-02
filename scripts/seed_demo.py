import random
import sys
from datetime import date
from pathlib import Path


# Allow importing backend.app...
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


from backend.app import config
from backend.app.database.connection import SessionLocal, engine
from backend.app.database.schema_check import require_current_schema
from backend.app.database.models import (
    Batch,
    Chapter,
    Institute,
    Question,
    Student,
    StudentAnswer,
    Test,
    Topic,
    User,
)
from backend.app.security.passwords import hash_password


# Demo sign-in accounts (demo databases only; never seeded in production).
DEMO_PASSWORD = "demo-password"
DEMO_USERS = (
    ("Demo Admin", "admin@demo.local", "admin"),
    ("Demo Teacher", "teacher@demo.local", "teacher"),
)

# Fixed seed so every fresh demo database contains the same data.
# This seed reproduces the Test 01 values documented in CLAUDE.md.
DEMO_SEED = 15173


def create_demo_data(seed=DEMO_SEED):
    if config.IS_PRODUCTION:
        raise SystemExit(
            "Refusing to seed demo data (and demo passwords) in production."
        )

    random.seed(seed)

    # The schema is created by migrations, never by this script:
    #   alembic upgrade head
    require_current_schema(engine)

    db = SessionLocal()

    try:
        if db.query(Institute).first() is not None:
            raise SystemExit(
                "The database already contains data. Seed only a fresh "
                "database (delete it, run `alembic upgrade head`, re-seed)."
            )

        # ---------------------------------------------------------
        # 1. Institute
        # ---------------------------------------------------------

        institute = Institute(
            name="ABC NEET Academy"
        )

        db.add(institute)
        db.flush()

        for name, email, role in DEMO_USERS:
            db.add(
                User(
                    institute_id=institute.id,
                    name=name,
                    email=email,
                    password_hash=hash_password(DEMO_PASSWORD),
                    role=role,
                    is_active=True,
                )
            )

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
                institute_id=institute.id,
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
                    batch_id=test.batch_id,
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
        print(
            "Sign in:   "
            + ", ".join(email for _, email, _ in DEMO_USERS)
            + f" (password: {DEMO_PASSWORD})"
        )
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
