"""Seed demo data for local development.

Usage: python manage.py seed_demo
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from datetime import timedelta
from pathlib import Path

from django.conf import settings

from apps.accounts.models import LecturerProfile, StudentProfile, User
from apps.accounts.matricule import build_matricule, is_valid_matricule
from apps.academics.models import (
    Semester,
    ClassDefinition,
    ClassSession,
    Course,
    CourseOffering,
    Department,
    Enrollment,
    Faculty,
)
from apps.announcements.models import Announcement
from apps.attendance.models import AttendanceCheckpoint, AttendanceRecord, AttendanceSession, PointsLedger
from apps.academics.models import ClassSchedule
from apps.projects.models import ClassDelegate, Project, ProjectGroup, ProjectMember, ProjectTask
from apps.learning.models import UploadedFile, LearningMaterial, Assignment, AssignmentSubmission


class Command(BaseCommand):
    help = "Seed demo data for the FET Platform"

    # Demo students are 2023 entrants in programme "A" -> FE23A001..FE23A005
    DEMO_ENTRY_YEAR = 2023
    DEMO_PROGRAMME_LETTER = "A"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Seed even when DEBUG is off. Only for a deliberate demo on a throwaway database.",
        )

    def handle(self, *args, **options):
        # This creates accounts with published, well-known passwords
        # (admin@fet.edu / admin123 and friends). On a production database that
        # is a backdoor, so refuse unless the operator insists.
        if not settings.DEBUG and not options.get("force"):
            raise CommandError(
                "seed_demo creates accounts with publicly documented passwords and "
                "refuses to run with DEBUG=False.\n"
                "Run it against a local SQLite database, or pass --force if you are "
                "certain this is a throwaway demo database."
            )

        self.stdout.write("Seeding FET Platform demo data...")

        # --- Faculty & Department ---
        fet, _ = Faculty.objects.get_or_create(
            code="FET", defaults={"name": "Faculty of Engineering and Technology", "description": "Engineering and Technology"}
        )
        # All FET departments (source: https://ubstudent.online/admission_programs)
        fet_departments = [
            {"code": "CIV", "name": "Civil Engineering",
             "description": "Offers M.Eng in Civil Engineering, B.Eng top-ups, environmental engineering, and related postgraduate programs."},
            {"code": "CEN", "name": "Computer Engineering",
             "description": "Offers B.Eng Computer Engineering (Network, Software, Telecommunication), M.Eng Computer Vision & AI, Cryptosystems & Cyber Security, Network Engineering and Software Engineering."},
            {"code": "CPE", "name": "Chemical and Petroleum Engineering",
             "description": "Offers B.Eng in Chemical and Petroleum Engineering."},
            {"code": "EEN", "name": "Electrical and Electronic Engineering",
             "description": "Offers B.Eng Electrical and Electronic Engineering (Power Systems, Telecommunication), M.Eng Power Systems, Telecommunications and Networks, and Renewable Energy."},
            {"code": "MEF", "name": "Mechanical and Industrial Engineering",
             "description": "Offers B.Eng in Mechanical Engineering, M.Eng in Energy, Industrial, Mechatronics, and related technology top-ups."},
        ]
        department_objs = {}
        for dept in fet_departments:
            dept_obj, _ = Department.objects.get_or_create(
                code=dept["code"],
                defaults={"faculty": fet, "name": dept["name"], "description": dept["description"]},
            )
            department_objs[dept["code"]] = dept_obj
        # Demo departments kept for backward compatibility with seeded demo data
        cs_dept, _ = Department.objects.get_or_create(
            code="CS", defaults={"faculty": fet, "name": "Computer Science", "description": "Computer Science Department"}
        )
        _ = department_objs

        # --- Semester ---
        semester1, _ = Semester.objects.get_or_create(
            academic_year="2026/2027", number="1",
            defaults={
                "name": "2026/2027 Semester 1",
                "start_date": timezone.now().date() - timedelta(days=14),
                "end_date": timezone.now().date() + timedelta(days=120),
            },
        )
        semester2, _ = Semester.objects.get_or_create(
            academic_year="2026/2027", number="2",
            defaults={
                "name": "2026/2027 Semester 2",
                "start_date": timezone.now().date() + timedelta(days=130),
                "end_date": timezone.now().date() + timedelta(days=250),
            },
        )
        semester1.is_active = True
        semester1.save(update_fields=["is_active"])
        semester2.is_active = False
        semester2.save(update_fields=["is_active"])

        # --- Users ---
        admin, _ = User.objects.get_or_create(
            email="admin@fet.edu",
            defaults={"first_name": "Admin", "last_name": "System", "role": "SYSTEM_ADMIN", "is_staff": True, "is_superuser": True},
        )
        admin.set_password("admin123")
        admin.save()

        lecturer, _ = User.objects.get_or_create(
            email="dr.smith@fet.edu",
            defaults={"first_name": "David", "last_name": "Smith", "role": "LECTURER"},
        )
        lecturer.set_password("lecturer123")
        lecturer.save()
        LecturerProfile.objects.get_or_create(
            user=lecturer,
            defaults={"staff_number": "STF001", "department": cs_dept, "title": "Dr."},
        )

        student_emails = [
            ("john.doe@student.fet.edu", "John", "Doe"),
            ("mary.smith@student.fet.edu", "Mary", "Smith"),
            ("peter.james@student.fet.edu", "Peter", "James"),
            ("sarah.brown@student.fet.edu", "Sarah", "Brown"),
            ("david.adams@student.fet.edu", "David", "Adams"),
        ]
        students = []
        for index, (email, first, last) in enumerate(student_emails, start=1):
            s, created = User.objects.get_or_create(
                email=email,
                defaults={"first_name": first, "last_name": last, "role": "STUDENT"},
            )
            if created:
                s.set_password("student123")
                s.save()
            profile, _ = StudentProfile.objects.get_or_create(
                user=s,
                defaults={
                    "student_number": build_matricule(
                        self.DEMO_ENTRY_YEAR, self.DEMO_PROGRAMME_LETTER, index
                    ),
                    "department": cs_dept,
                    "level": "300",
                },
            )
            # Older databases were seeded with email-derived numbers such as
            # JOHNDOE. Bring them onto the real FET format on re-seed.
            if not is_valid_matricule(profile.student_number):
                profile.student_number = build_matricule(
                    self.DEMO_ENTRY_YEAR, self.DEMO_PROGRAMME_LETTER, index
                )
                profile.save(update_fields=["student_number", "updated_at"])
            students.append(s)

        # --- Courses ---
        csc301, _ = Course.objects.get_or_create(
            code="CSC301", defaults={"department": cs_dept, "title": "Database Systems", "credit_units": 3, "level": "300"}
        )
        csc302, _ = Course.objects.get_or_create(
            code="CSC302", defaults={"department": cs_dept, "title": "Software Engineering", "credit_units": 3, "level": "300"}
        )
        # A CS course with NO classroom yet, so a lecturer can demo the
        # "Create classroom" flow (auto-enrols the registered cohort).
        Course.objects.get_or_create(
            code="CSC305", defaults={"department": cs_dept, "title": "Computer Networks", "credit_units": 3, "level": "300"}
        )

        # Computer Engineering L200 courses (Semester 1)
        cen_l200_courses = [
            {"code": "CEF201", "title": "Analysis", "credit_units": 4},
            {"code": "CEF203", "title": "Linear Algebra", "credit_units": 4},
            {"code": "CEF205", "title": "Introduction to Computing", "credit_units": 4},
            {"code": "CEF207", "title": "Programming I", "credit_units": 4},
            {"code": "CEF211", "title": "Boolean Algebra and Logic Circuits", "credit_units": 4},
            {"code": "EEF261", "title": "Circuit Analysis", "credit_units": 4},
            {"code": "EEF263", "title": "Digital Electronics I", "credit_units": 4},
            {"code": "EEF269", "title": "Physics for Engineering I", "credit_units": 4},
        ]
        cen_dept = department_objs["CEN"]
        for c in cen_l200_courses:
            Course.objects.get_or_create(
                code=c["code"],
                defaults={"department": cen_dept, "title": c["title"], "credit_units": c["credit_units"], "level": "200"},
            )

        # --- Course Offerings (CEN L200, Semester 1) ---
        for c in cen_l200_courses:
            course_obj = Course.objects.get(code=c["code"])
            CourseOffering.objects.get_or_create(
                course=course_obj, semester=semester1,
                defaults={"department": cen_dept},
            )

        # Computer Engineering L200 courses (Semester 2)
        cen_l200_s2_courses = [
            {"code": "CEF250", "title": "Computer Architecture", "credit_units": 4},
            {"code": "CEF238", "title": "C/C++ Programming", "credit_units": 4},
            {"code": "CEF254", "title": "Algebra", "credit_units": 4},
            {"code": "EEF260", "title": "Analog Electronics I", "credit_units": 4},
            {"code": "EEF262", "title": "Physics for Engineering II", "credit_units": 4},
            {"code": "EEF264", "title": "Control Engineering Instrumentation", "credit_units": 3},
            {"code": "EEF268", "title": "Digital Electronics II", "credit_units": 4},
        ]

        # Computer Engineering L300 courses (Semester 1)
        cen_l300_s1_courses = [
            {"code": "CEF333", "title": "Hardware and Software Maintenance", "credit_units": 3},
            {"code": "CEF347", "title": "Operating Systems", "credit_units": 3},
            {"code": "CEF349", "title": "Analysis and Design of Information Systems", "credit_units": 3},
            {"code": "CEF331", "title": "Object Oriented Modeling and UML", "credit_units": 3},
            {"code": "CEF345", "title": "Software Development Tools (AGL L5G)", "credit_units": 3},
            {"code": "CEF341", "title": "Algorithms and Data Structure", "credit_units": 3},
            {"code": "EEF363", "title": "Analog Electronics II", "credit_units": 4},
            {"code": "EEF365", "title": "Microcontrollers and Microprocessors", "credit_units": 3},
            {"code": "EEF367", "title": "Digital Electronic Laboratory", "credit_units": 4},
            {"code": "FET301", "title": "Probability and Statistics", "credit_units": 3},
        ]

        # Computer Engineering L300 courses (Semester 2)
        cen_l300_s2_courses = [
            {"code": "CEF342", "title": "Database and Design", "credit_units": 3},
            {"code": "CEF344", "title": "Client-Server and Web Application Development (PHP, JavaScript, XML, J2EE)", "credit_units": 3},
            {"code": "CEF346", "title": "Object Oriented Programming (Java/C++)", "credit_units": 3},
            {"code": "CEF350", "title": "Security and Cryptosystem", "credit_units": 3},
            {"code": "CEF352", "title": "Tools and Numerical Methods for Engineering", "credit_units": 3},
            {"code": "CEF354", "title": "Switching and Routing Protocols", "credit_units": 3},
            {"code": "CEF356", "title": "Mobile Communications and Protocols", "credit_units": 3},
            {"code": "CEF364", "title": "Local Area Computer Networks", "credit_units": 3},
            {"code": "EEF362", "title": "Analog Electronics Laboratory", "credit_units": 4},
            {"code": "EEF368", "title": "Microcontroller and Microprocessors Laboratory", "credit_units": 3},
        ]
        for c in cen_l300_s1_courses:
            Course.objects.get_or_create(
                code=c["code"],
                defaults={"department": cen_dept, "title": c["title"], "credit_units": c["credit_units"], "level": "300"},
            )

        # Computer Engineering L300 courses (Semester 2)
        cen_l300_s2_courses = [
            {"code": "CEF342", "title": "Database and Design", "credit_units": 3},
            {"code": "CEF344", "title": "Client-Server and Web Application Development (PHP, JavaScript, XML, J2EE)", "credit_units": 3},
            {"code": "CEF346", "title": "Object Oriented Programming (Java/C++)", "credit_units": 3},
            {"code": "CEF350", "title": "Security and Cryptosystem", "credit_units": 3},
            {"code": "CEF352", "title": "Tools and Numerical Methods for Engineering", "credit_units": 3},
            {"code": "CEF354", "title": "Switching and Routing Protocols", "credit_units": 3},
            {"code": "CEF356", "title": "Mobile Communications and Protocols", "credit_units": 3},
            {"code": "CEF364", "title": "Local Area Computer Networks", "credit_units": 3},
            {"code": "EEF362", "title": "Analog Electronics Laboratory", "credit_units": 4},
            {"code": "EEF368", "title": "Microcontroller and Microprocessors Laboratory", "credit_units": 3},
        ]
        for c in cen_l300_s2_courses:
            Course.objects.get_or_create(
                code=c["code"],
                defaults={"department": cen_dept, "title": c["title"], "credit_units": c["credit_units"], "level": "300"},
            )

        for c in cen_l200_s2_courses:
            Course.objects.get_or_create(
                code=c["code"],
                defaults={"department": cen_dept, "title": c["title"], "credit_units": c["credit_units"], "level": "200"},
            )

        # --- Course Offerings (CEN L200, Semester 2) ---
        for c in cen_l200_s2_courses:
            course_obj = Course.objects.get(code=c["code"])
            CourseOffering.objects.get_or_create(
                course=course_obj, semester=semester2,
                defaults={"department": cen_dept},
            )

        # --- Course Offerings (CEN L300, Semester 1) ---
        for c in cen_l300_s1_courses:
            course_obj = Course.objects.get(code=c["code"])
            CourseOffering.objects.get_or_create(
                course=course_obj, semester=semester1,
                defaults={"department": cen_dept},
            )

        # --- Course Offerings (CEN L300, Semester 2) ---
        for c in cen_l300_s2_courses:
            course_obj = Course.objects.get(code=c["code"])
            CourseOffering.objects.get_or_create(
                course=course_obj, semester=semester2,
                defaults={"department": cen_dept},
            )

        off301, _ = CourseOffering.objects.get_or_create(
            course=csc301, semester=semester1,
            defaults={"department": cs_dept, "lecturer": lecturer},
        )
        off302, _ = CourseOffering.objects.get_or_create(
            course=csc302, semester=semester1,
            defaults={"department": cs_dept, "lecturer": lecturer},
        )

        # --- Enrollments ---
        for student in students:
            Enrollment.objects.get_or_create(
                student=student, course_offering=off301,
                defaults={"status": Enrollment.Status.ACTIVE},
            )
            if student.email in ("john.doe@student.fet.edu", "mary.smith@student.fet.edu"):
                Enrollment.objects.get_or_create(
                    student=student, course_offering=off302,
                    defaults={"status": Enrollment.Status.ACTIVE},
                )

        # --- Class Definitions ---
        lecture_def, _ = ClassDefinition.objects.get_or_create(
            course_offering=off301, name="Database Systems - Monday Lecture",
            defaults={"lecturer": lecturer, "class_type": "LECTURE", "location": "Room 204"},
        )
        practical_def, _ = ClassDefinition.objects.get_or_create(
            course_offering=off301, name="Database Systems - Wednesday Practical",
            defaults={"lecturer": lecturer, "class_type": "PRACTICAL", "location": "Lab 3"},
        )
        se_lecture_def, _ = ClassDefinition.objects.get_or_create(
            course_offering=off302, name="Software Engineering - Tuesday Lecture",
            defaults={"lecturer": lecturer, "class_type": "LECTURE", "location": "Room 101"},
        )

        # --- Weekly Timetable (ClassSchedule) ---
        ClassSchedule.objects.get_or_create(
            course_offering=off301, day_of_week="MONDAY", start_time="10:00",
            defaults={"lecturer": lecturer, "class_type": "LECTURE", "end_time": "12:00", "location": "Room 204"},
        )
        ClassSchedule.objects.get_or_create(
            course_offering=off301, day_of_week="WEDNESDAY", start_time="14:00",
            defaults={"lecturer": lecturer, "class_type": "PRACTICAL", "end_time": "16:00", "location": "Lab 3"},
        )
        ClassSchedule.objects.get_or_create(
            course_offering=off302, day_of_week="TUESDAY", start_time="08:00",
            defaults={"lecturer": lecturer, "class_type": "LECTURE", "end_time": "10:00", "location": "Room 101"},
        )

        # --- Class Sessions ---
        now = timezone.now()
        session_today, _ = ClassSession.objects.get_or_create(
            class_definition=lecture_def,
            starts_at=now + timedelta(hours=1),
            defaults={"ends_at": now + timedelta(hours=3), "status": "SCHEDULED"},
        )
        session_tomorrow, _ = ClassSession.objects.get_or_create(
            class_definition=se_lecture_def,
            starts_at=now + timedelta(days=1, hours=2),
            defaults={"ends_at": now + timedelta(days=1, hours=4), "status": "SCHEDULED"},
        )
        # A session for today (past, for attendance demo)
        session_past, _ = ClassSession.objects.get_or_create(
            class_definition=practical_def,
            starts_at=now - timedelta(hours=2),
            defaults={"ends_at": now - timedelta(hours=1), "status": "COMPLETED"},
        )

        # --- Attendance Session (demo) ---
        # Past/EXPIRED so it never shows a live station banner. The station is
        # TEACHER-picked (never AUTO) to stay consistent with the presence-gated
        # auto-select rules (AUTO requires 15 checked-in students).
        past_day = (now - timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        demo_class_session, _ = ClassSession.objects.get_or_create(
            class_definition=practical_def,
            starts_at=past_day,
            defaults={"ends_at": past_day + timedelta(hours=2), "status": "COMPLETED"},
        )
        att_session, _ = AttendanceSession.objects.get_or_create(
            class_session=demo_class_session,
            defaults={
                "lecturer": lecturer,
                "started_at": past_day,
                "expires_at": past_day + timedelta(seconds=60),
                "status": AttendanceSession.Status.EXPIRED,
            },
        )
        if students:
            cp, _ = AttendanceCheckpoint.objects.get_or_create(
                attendance_session=att_session, student=students[0],
                defaults={
                    "checkpoint_number": 1,
                    "selection_method": AttendanceCheckpoint.SelectionMethod.TEACHER,
                },
            )
            # Everyone present got a record; the station owner also earned points.
            for s in students[:3]:
                AttendanceRecord.objects.get_or_create(
                    attendance_session=att_session, student=s,
                    defaults={"checkpoint": cp if s == students[0] else None, "status": "PRESENT"},
                )
            PointsLedger.objects.get_or_create(
                student=students[0], attendance_session=att_session,
                defaults={"category": PointsLedger.Category.TEACHER_STATION, "points": 5},
            )
            for s in students[1:3]:
                PointsLedger.objects.get_or_create(
                    student=s, attendance_session=att_session,
                    defaults={"category": PointsLedger.Category.SCAN, "points": 3},
                )

        # --- Projects ---
        # One of each scope so every workflow can be demonstrated:
        #   INDIVIDUAL     every student submits their own copy
        #   CLASS_WIDE     the class forms groups, all groups work together
        #   GROUP_SPECIFIC an independent project handed to a single group
        individual_proj, _ = Project.objects.get_or_create(
            title="Individual Research Report",
            defaults={
                "course_offering": off301,
                "created_by": lecturer,
                "supervisor": lecturer,
                "description": "Each student writes their own report on a topic of their choice.",
                "objectives": "Literature review\nMethodology\n1500-word report",
                "status": Project.Status.ACTIVE,
                "scope": Project.Scope.INDIVIDUAL,
            },
        )
        for student in students:
            ProjectMember.objects.get_or_create(
                project=individual_proj, student=student, defaults={"role": "MEMBER"}
            )

        proj, _ = Project.objects.get_or_create(
            title="Attendance Management System",
            defaults={
                "course_offering": off301,
                "created_by": lecturer,
                "supervisor": lecturer,
                "description": "Build a modern attendance management platform with QR-based check-in. "
                               "The class is split into groups that all work towards the same goal.",
                "objectives": "QR check-in\nLecturer dashboard\nReporting",
                "status": Project.Status.ACTIVE,
                "scope": Project.Scope.CLASS_WIDE,
            },
        )
        # get_or_create leaves an existing row untouched, so bring a project
        # seeded by an older version of this command up to date explicitly.
        if proj.scope != Project.Scope.CLASS_WIDE or proj.group_id is not None:
            proj.scope = Project.Scope.CLASS_WIDE
            proj.group = None
            proj.save(update_fields=["scope", "group", "updated_at"])

        # Keep the whole class on the roster, mirroring auto-enrolment.
        for student in students:
            ProjectMember.objects.get_or_create(
                project=proj, student=student, defaults={"role": "MEMBER"}
            )

        group, _ = ProjectGroup.objects.get_or_create(project=proj, name="Group A")
        team_b, _ = ProjectGroup.objects.get_or_create(project=proj, name="Group B")

        def place(student, target_group, role="MEMBER"):
            """Put a student in a group, overwriting a previous placement."""
            member, _made = ProjectMember.objects.get_or_create(
                project=proj, student=student, defaults={"role": role}
            )
            if member.group_id != target_group.id or member.role != role:
                member.group = target_group
                member.role = role
                member.save(update_fields=["group", "role", "updated_at"])

        # Group A takes the first three; Group B takes the next one. The last
        # student is deliberately left ungrouped so the lecturer's "Unassigned"
        # bucket has something in it.
        for student in students[:3]:
            place(student, group, "GROUP_LEADER" if student == students[0] else "MEMBER")
        group.leader = students[0]
        group.save(update_fields=["leader", "updated_at"])

        if len(students) > 3:
            place(students[3], team_b, "GROUP_LEADER")
            team_b.leader = students[3]
            team_b.save(update_fields=["leader", "updated_at"])

        tasks_data = [
            ("Design database schema", "COMPLETED", students[0]),
            ("Build authentication system", "IN_PROGRESS", students[1]),
            ("Implement QR scanning", "TODO", students[2]),
            ("Write API documentation", "TODO", students[0]),
        ]
        for title, task_status, assignee in tasks_data:
            ProjectTask.objects.get_or_create(
                project=proj, title=title,
                defaults={"created_by": lecturer, "assigned_student": assignee, "status": task_status, "group": group},
            )

        # A second project running at the same time, handed to Group B only.
        sub_proj, _ = Project.objects.get_or_create(
            title="Group B - Library Portal",
            defaults={
                "course_offering": off301,
                "created_by": lecturer,
                "supervisor": lecturer,
                "description": "An independent project for Group B: a catalogue and lending portal.",
                "status": Project.Status.ACTIVE,
                "scope": Project.Scope.GROUP_SPECIFIC,
                "group": team_b,
            },
        )
        if sub_proj.scope != Project.Scope.GROUP_SPECIFIC or sub_proj.group_id != team_b.id:
            sub_proj.scope = Project.Scope.GROUP_SPECIFIC
            sub_proj.group = team_b
            sub_proj.save(update_fields=["scope", "group", "updated_at"])
        for member in team_b.members.select_related("student"):
            sub_member, _made = ProjectMember.objects.get_or_create(
                project=sub_proj, student=member.student,
                defaults={"group": team_b, "role": member.role},
            )
            if sub_member.group_id != team_b.id:
                sub_member.group = team_b
                sub_member.save(update_fields=["group", "updated_at"])
        ProjectTask.objects.get_or_create(
            project=sub_proj, title="Model books and borrowers",
            defaults={"created_by": lecturer, "group": team_b, "priority": "HIGH"},
        )

        # A class delegate who can form groups on the lecturer's behalf.
        ClassDelegate.objects.get_or_create(
            course_offering=off301,
            defaults={"student": students[0], "appointed_by": lecturer},
        )

        # --- Announcements ---
        Announcement.objects.get_or_create(
            title="Welcome to 2026/2027 Semester 1",
            defaults={
                "created_by": admin,
                "scope_type": "FACULTY",
                "faculty": fet,
                "content": "Welcome to a new semester! Please check your course schedules and enrolled classes.",
                "published_at": now,
            },
        )
        Announcement.objects.get_or_create(
            title="Database Systems - First Class Reminder",
            defaults={
                "created_by": lecturer,
                "scope_type": "COURSE",
                "course_offering": off301,
                "content": "Our first Database Systems class is scheduled for this Monday. Please bring your laptops.",
                "published_at": now,
            },
        )

        # --- Learning: Materials / Assignments (Classroom) ---
        def seed_file(name, text, uploaded_by, mime_type="text/plain"):
            root = Path(settings.MEDIA_ROOT)
            sub = root / "uploaded" / "seed"
            sub.mkdir(parents=True, exist_ok=True)
            path = sub / name
            if not path.exists():
                path.write_text(text, encoding="utf-8")
            storage_key = f"uploaded/seed/{name}"
            fobj, _ = UploadedFile.objects.get_or_create(
                storage_key=storage_key,
                defaults=dict(uploaded_by=uploaded_by, original_name=name, mime_type=mime_type, size_bytes=path.stat().st_size),
            )
            return fobj

        f_lect1 = seed_file("db-lecture1.txt", "CSC301 Lecture 1: Relational model\nER diagrams, keys, normalization intro.\n", lecturer)
        f_lect2 = seed_file("db-lecture2.txt", "CSC301 Lecture 2: SQL fundamentals\nDDL, DML, joins, transactions.\n", lecturer)
        f_brief = seed_file("db-quiz-brief.txt", "Quiz 1: Write SQL for the campus library schema.\nSubmit a single .sql file.", lecturer)
        f_quiz = seed_file("john-sql.txt", "-- SQL practice submission by John\nSELECT * FROM books WHERE category='CS';\n", students[0])

        LearningMaterial.objects.get_or_create(
            course_offering=off301, title="Lecture 1 - Relational Model",
            defaults=dict(uploaded_by=lecturer, description="ER diagrams, keys, normalization intro.", file=f_lect1, visibility="COURSE"),
        )
        LearningMaterial.objects.get_or_create(
            course_offering=off301, title="Lecture 2 - SQL Fundamentals",
            defaults=dict(uploaded_by=lecturer, description="DDL, DML, joins, transactions.", file=f_lect2, visibility="COURSE"),
        )
        LearningMaterial.objects.get_or_create(
            course_offering=off301, title="Recommended Reading - Elmasri & Navathe",
            defaults=dict(uploaded_by=lecturer, description="Chapters 3-4 cover the ER model and relational mapping.", file=None, visibility="COURSE"),
        )
        LearningMaterial.objects.get_or_create(
            course_offering=off302, title="Lecture 1 - SDLC",
            defaults=dict(uploaded_by=lecturer, description="Software life-cycle overview and requirements engineering.", file=None, visibility="COURSE"),
        )

        asgn_quiz, _ = Assignment.objects.get_or_create(
            course_offering=off301, title="Quiz 1 - SQL Practice",
            defaults=dict(
                created_by=lecturer, description="Complete the SQL queries for the campus library schema.",
                points_possible=20, due_at=now + timedelta(days=5), allow_late=False,
                max_submissions=1, attachment=f_brief, status="ACTIVE",
            ),
        )
        Assignment.objects.get_or_create(
            course_offering=off301, title="Database Design Project - Phase 1",
            defaults=dict(
                created_by=lecturer, description="ER model + relational schema + rationale (report PDF).",
                points_possible=50, due_at=now + timedelta(days=21), allow_late=True,
                max_submissions=3, attachment=None, status="ACTIVE",
            ),
        )
        Assignment.objects.get_or_create(
            course_offering=off301, title="ER Diagram exercise (closed)",
            defaults=dict(
                created_by=lecturer, description="ER diagram for the enrollment system.",
                points_possible=10, due_at=now - timedelta(days=7), allow_late=False,
                max_submissions=2, attachment=None, status="ACTIVE",
            ),
        )
        Assignment.objects.get_or_create(
            course_offering=off302, title="Requirements Analysis Report",
            defaults=dict(
                created_by=lecturer, description="Write a requirements specification for a chosen system (5-8 pages).",
                points_possible=30, due_at=now + timedelta(days=14), allow_late=True,
                max_submissions=2, attachment=None, status="ACTIVE",
            ),
        )
        AssignmentSubmission.objects.get_or_create(
            assignment=asgn_quiz, student=students[0],
            defaults=dict(
                file=f_quiz, note="Submitted early.",
                status="GRADED", is_late=False, grade="16.00",
                feedback="Good joins, watch NULL handling.", graded_by=lecturer, graded_at=now - timedelta(hours=2),
            ),
        )

        self.stdout.write(self.style.SUCCESS(
            "Demo data seeded successfully!\n"
            "\nCredentials:\n"
            "  Admin:    admin@fet.edu / admin123\n"
            "  Lecturer: dr.smith@fet.edu / lecturer123\n"
            "  Students: john.doe@student.fet.edu / student123\n"
            "            mary.smith@student.fet.edu / student123\n"
        ))
