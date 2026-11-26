import pytest

from accounts.services.email_policy import agency_of, is_admin_email, is_user_email


@pytest.mark.parametrize(
    "email",
    ["govfleetadmin01@dict.gov.ph", "govfleetadmin02@dost.gov.ph", " GovFleetAdmin99@DICT.gov.ph "],
)
def test_admin_emails(email):
    assert is_admin_email(email)
    assert not is_user_email(email)


@pytest.mark.parametrize(
    "email",
    [
        "govfleetadmin1@dict.gov.ph",  # needs two digits
        "govfleetadmin001@dict.gov.ph",
        "govfleetadmin01@dict.gov.ph.evil.com",
        "govfleetadmin01@gmail.com",
        "govfleetadmin01@dict.gov",
        "xgovfleetadmin01@dict.gov.ph",
    ],
)
def test_not_admin_emails(email):
    assert not is_admin_email(email)


@pytest.mark.parametrize("email", ["kcdimayuga@dict.gov.ph", "juandelacruz@dost.gov.ph", "KCDimayuga@DICT.gov.ph"])
def test_user_emails(email):
    assert is_user_email(email)


@pytest.mark.parametrize(
    "email",
    [
        "kc.dimayuga@dict.gov.ph",  # letters only
        "kcdimayuga2@dict.gov.ph",
        "kcdimayuga@gmail.com",
        "kcdimayuga@dict.gov.ph.example.com",
        "govfleetadmin@dict.gov.ph",  # reserved prefix
        "govfleetadminx@dict.gov.ph",
        "k@dict.gov.ph",  # too short
        "",
        None,
    ],
)
def test_not_user_emails(email):
    assert not is_user_email(email)


def test_agency_comes_from_domain():
    assert agency_of("kcdimayuga@dict.gov.ph") == "dict"
    assert agency_of("govfleetadmin02@dost.gov.ph") == "dost"
    assert agency_of("someone@gmail.com") == ""
