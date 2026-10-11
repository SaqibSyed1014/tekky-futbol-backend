from django.urls import reverse
from rest_framework import status

from apps.tickets.models import Staff
from apps.users.tests.base import BaseAPITestCase

STAFF_LIST_URL = reverse("api_admin:admin_staff_list")


def _detail_url(staff_id):
    return reverse("api_admin:admin_staff_detail", kwargs={"pk": str(staff_id)})


class AdminStaffListCreateTests(BaseAPITestCase):
    def test_unauthenticated_returns_401(self):
        response = self.client.get(STAFF_LIST_URL)
        self.assert_status(response, status.HTTP_401_UNAUTHORIZED)

    def test_non_admin_returns_403(self):
        self.authenticate_as(self.create_fan())
        response = self.client.get(STAFF_LIST_URL)
        self.assert_status(response, status.HTTP_403_FORBIDDEN)

    def test_admin_can_create_staff_with_admin_chosen_id(self):
        self.authenticate_as(self.create_admin())
        response = self.client.post(STAFF_LIST_URL, {
            "name": "Jordan Gate",
            "email": "jordan@test.com",
            "unique_id": "482913",
        })

        self.assert_status(response, status.HTTP_201_CREATED)
        self.assertEqual(response.data["unique_id"], "482913")
        staff = Staff.objects.get(name="Jordan Gate")
        self.assertEqual(staff.unique_id, "482913")  # exactly what the admin typed, not generated

    def test_email_is_optional(self):
        self.authenticate_as(self.create_admin())
        response = self.client.post(STAFF_LIST_URL, {"name": "No Email Staffer", "unique_id": "111111"})
        self.assert_status(response, status.HTTP_201_CREATED)
        self.assertEqual(response.data["email"], "")

    def test_unique_id_must_be_six_digits(self):
        self.authenticate_as(self.create_admin())
        for bad_id in ["12345", "1234567", "12a456", ""]:
            response = self.client.post(STAFF_LIST_URL, {"name": "Test", "unique_id": bad_id})
            self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_unique_id_is_rejected(self):
        self.authenticate_as(self.create_admin())
        Staff.objects.create(name="First", unique_id="555555")

        response = self.client.post(STAFF_LIST_URL, {"name": "Second", "unique_id": "555555"})
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Staff.objects.filter(unique_id="555555").count(), 1)

    def test_name_is_required(self):
        self.authenticate_as(self.create_admin())
        response = self.client.post(STAFF_LIST_URL, {"unique_id": "222222"})
        self.assert_status(response, status.HTTP_400_BAD_REQUEST)

    def test_list_returns_all_staff(self):
        Staff.objects.create(name="Alice", unique_id="111111")
        Staff.objects.create(name="Bob", unique_id="222222")

        self.authenticate_as(self.create_admin())
        response = self.client.get(STAFF_LIST_URL)

        self.assert_status(response, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)


class AdminStaffDeleteTests(BaseAPITestCase):
    def test_admin_can_delete_staff(self):
        staff = Staff.objects.create(name="To Remove", unique_id="333333")

        self.authenticate_as(self.create_admin())
        response = self.client.delete(_detail_url(staff.id))

        self.assert_status(response, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Staff.objects.filter(id=staff.id).exists())

    def test_non_admin_cannot_delete(self):
        staff = Staff.objects.create(name="Protected", unique_id="444444")

        self.authenticate_as(self.create_fan())
        response = self.client.delete(_detail_url(staff.id))

        self.assert_status(response, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Staff.objects.filter(id=staff.id).exists())

    def test_deleting_unknown_staff_returns_404(self):
        import uuid
        self.authenticate_as(self.create_admin())
        response = self.client.delete(_detail_url(uuid.uuid4()))
        self.assert_status(response, status.HTTP_404_NOT_FOUND)
