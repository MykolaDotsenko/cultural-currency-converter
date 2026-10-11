"""Recovery email identity cannot confer trust without confirmed ownership."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import VerifiedRecoveryEmail


@pytest.mark.django_db
def test_unverified_email_never_claims_recovery_privileges():
    owner = get_user_model().objects.create_user(
        username="recovery-pending",
        email="unverified@example.test",
    )
    # Legacy auth.User.email is never implicitly trusted or imported.
    assert not VerifiedRecoveryEmail.objects.filter(user=owner).exists()
    identity = VerifiedRecoveryEmail.objects.create(
        user=owner,
        email="  OWNER@EXAMPLE.TEST  ",
    )
    identity.refresh_from_db()
    assert identity.email == "owner@example.test"
    assert identity.is_verified is False
    assert identity.verified_at is None
    assert "owner@example.test" not in str(identity)


@pytest.mark.django_db
def test_multiple_pending_contacts_cannot_block_same_owners_email_claim():
    User = get_user_model()
    alice = User.objects.create_user(username="pending-alice")
    bob = User.objects.create_user(username="pending-bob")
    a = VerifiedRecoveryEmail.objects.create(user=alice, email="shared@example.test")
    b = VerifiedRecoveryEmail.objects.create(user=bob, email="SHARED@example.test")
    assert a.is_verified is False
    assert b.is_verified is False
    assert VerifiedRecoveryEmail.objects.count() == 2


@pytest.mark.django_db
def test_verified_email_is_case_insensitive_unique_even_after_direct_sql_update():
    User = get_user_model()
    alice = User.objects.create_user(username="verified-alice")
    bob = User.objects.create_user(username="verified-bob")
    email_a = VerifiedRecoveryEmail.objects.create(
        user=alice,
        email="owner@example.test",
        verified_at=timezone.now(),
    )
    email_b = VerifiedRecoveryEmail.objects.create(
        user=bob,
        email="OWNER@example.test",
    )
    assert email_a.is_verified
    with pytest.raises(IntegrityError), transaction.atomic():
        VerifiedRecoveryEmail.objects.filter(pk=email_b.pk).update(
            verified_at=timezone.now(),
        )
    email_b.refresh_from_db()
    assert not email_b.is_verified


@pytest.mark.django_db
def test_email_identity_ownership_is_one_to_one():
    user = get_user_model().objects.create_user(username="one-email-owner")
    VerifiedRecoveryEmail.objects.create(user=user, email="one@example.test")
    with pytest.raises(IntegrityError), transaction.atomic():
        VerifiedRecoveryEmail.objects.create(user=user, email="two@example.test")


@pytest.mark.django_db
def test_email_identity_uses_django_email_validation_before_verification():
    user = get_user_model().objects.create_user(username="invalid-email-owner")
    identity = VerifiedRecoveryEmail(user=user, email="not a valid email")
    with pytest.raises(ValidationError):
        identity.full_clean()


@pytest.mark.django_db
def test_account_deletion_cascades_recovery_email_identity():
    user = get_user_model().objects.create_user(username="erase-identity")
    VerifiedRecoveryEmail.objects.create(user=user, email="owner@example.test")
    user.delete()
    assert not VerifiedRecoveryEmail.objects.exists()
