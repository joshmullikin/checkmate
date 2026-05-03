import json

from db.models import Environment, NotificationChannel, RunStatus, Schedule, ScheduledRun, TestCase, TestData, TestFolder


class TestModelSetters:
    def test_project_set_config(self):
        from db.models import Project

        project = Project(name="t", base_url="u", config="{}", next_test_case_number=1)
        project.set_config({"env": "prod"})
        assert json.loads(project.config) == {"env": "prod"}

    def test_testfolder_set_smart_criteria(self):
        folder = TestFolder(
            name="smart",
            project_id=1,
            folder_type="smart",
            smart_criteria="{}",
        )
        folder.set_smart_criteria({"tags": ["smoke"]})
        assert json.loads(folder.smart_criteria) == {"tags": ["smoke"]}

    def test_testcase_set_steps(self):
        test_case = TestCase(name="tc", natural_query="q", steps="[]", project_id=1)
        test_case.set_steps([{"action": "click"}])
        assert json.loads(test_case.steps)[0]["action"] == "click"

    def test_testcase_set_tags(self):
        test_case = TestCase(name="tc", natural_query="q", steps="[]", project_id=1)
        test_case.set_tags(["smoke", "regression"])
        assert json.loads(test_case.tags) == ["smoke", "regression"]

    def test_testcase_set_fixture_ids(self):
        test_case = TestCase(name="tc", natural_query="q", steps="[]", project_id=1)
        test_case.set_fixture_ids([1, 2, 3])
        assert json.loads(test_case.fixture_ids) == [1, 2, 3]

    def test_fixture_set_setup_steps(self):
        from db.models import Fixture

        fixture = Fixture(
            name="fx",
            setup_steps="[]",
            scope="cached",
            cache_ttl_seconds=3600,
            project_id=1,
        )
        fixture.set_setup_steps([{"action": "navigate", "value": "/login"}])
        assert json.loads(fixture.setup_steps)[0]["action"] == "navigate"

    def test_notification_channel_set_email_recipients(self):
        channel = NotificationChannel(name="ch", project_id=1)
        channel.set_email_recipients(["a@b.com", "c@d.com"])
        assert json.loads(channel.email_recipients) == ["a@b.com", "c@d.com"]

    def test_schedule_set_target_test_case_ids(self):
        schedule = Schedule(
            name="s",
            cron_expression="0 * * * *",
            project_id=1,
            target_type="test_case_ids",
        )
        schedule.set_target_test_case_ids([10, 20])
        assert json.loads(schedule.target_test_case_ids) == [10, 20]

    def test_schedule_set_target_tags(self):
        schedule = Schedule(
            name="s",
            cron_expression="0 * * * *",
            project_id=1,
            target_type="tags",
        )
        schedule.set_target_tags(["smoke"])
        assert json.loads(schedule.target_tags) == ["smoke"]

    def test_schedule_set_notification_channel_ids(self):
        schedule = Schedule(name="s", cron_expression="0 * * * *", project_id=1)
        schedule.set_notification_channel_ids([5, 6])
        assert json.loads(schedule.notification_channel_ids) == [5, 6]

    def test_scheduled_run_set_notifications_sent(self):
        scheduled_run = ScheduledRun(
            schedule_id=1,
            project_id=1,
            thread_id="t",
            status=RunStatus.PENDING,
        )
        scheduled_run.set_notifications_sent([3, 7])
        assert json.loads(scheduled_run.notifications_sent) == [3, 7]

    def test_scheduled_run_set_notification_errors(self):
        scheduled_run = ScheduledRun(
            schedule_id=1,
            project_id=1,
            thread_id="t",
            status=RunStatus.PENDING,
        )
        scheduled_run.set_notification_errors({"5": "timeout"})
        assert json.loads(scheduled_run.notification_errors) == {"5": "timeout"}

    def test_test_data_set_data(self):
        test_data = TestData(name="td", data="{}", project_id=1)
        test_data.set_data({"key": "val"})
        assert json.loads(test_data.data) == {"key": "val"}

    def test_test_data_set_tags(self):
        test_data = TestData(name="td", data="{}", project_id=1)
        test_data.set_tags(["users"])
        assert json.loads(test_data.tags) == ["users"]

    def test_environment_set_variables(self):
        environment = Environment(
            name="DEV",
            base_url="https://dev.example.com",
            project_id=1,
            variables="{}",
        )
        environment.set_variables({"BASE_URL": "https://dev.example.com"})
        assert json.loads(environment.variables)["BASE_URL"] == "https://dev.example.com"


class TestModelNullGetters:
    def test_notification_channel_get_email_recipients_none(self):
        channel = NotificationChannel(name="ch", project_id=1)
        assert channel.get_email_recipients() == []

    def test_schedule_get_target_test_case_ids_none(self):
        schedule = Schedule(name="s", cron_expression="* * * * *", project_id=1)
        assert schedule.get_target_test_case_ids() == []

    def test_schedule_get_target_tags_none(self):
        schedule = Schedule(name="s", cron_expression="* * * * *", project_id=1)
        assert schedule.get_target_tags() == []

    def test_schedule_get_notification_channel_ids_none(self):
        schedule = Schedule(name="s", cron_expression="* * * * *", project_id=1)
        assert schedule.get_notification_channel_ids() == []

    def test_scheduled_run_get_notifications_sent_none(self):
        scheduled_run = ScheduledRun(
            schedule_id=1,
            project_id=1,
            thread_id="t",
            status=RunStatus.PENDING,
        )
        assert scheduled_run.get_notifications_sent() == []

    def test_scheduled_run_get_notification_errors_none(self):
        scheduled_run = ScheduledRun(
            schedule_id=1,
            project_id=1,
            thread_id="t",
            status=RunStatus.PENDING,
        )
        assert scheduled_run.get_notification_errors() == {}

    def test_test_data_get_data_none(self):
        test_data = TestData(name="td", data=None, project_id=1)
        assert test_data.get_data() == {}

    def test_test_data_get_tags_none(self):
        test_data = TestData(name="td", data="{}", project_id=1, tags=None)
        assert test_data.get_tags() == []

    def test_environment_get_variables_none(self):
        environment = Environment(name="ENV", base_url="https://x.com", project_id=1, variables=None)
        assert environment.get_variables() == {}
