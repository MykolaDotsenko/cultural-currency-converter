from django.test import override_settings
from django.urls import reverse


@override_settings(VITE_DEV_SERVER_ENABLED=True)
def test_saved_state_page_is_anonymous_browser_local_shell(client):
    response = client.get(reverse("saved_state"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Saved &amp; recent" in content
    assert "stored only in this browser" in content.lower()
    assert "data-local-saved-state-page" in content
    assert "data-local-storage-status" in content
    assert "Checking browser storage" in content
    assert "Checking saved pairs in this browser" in content
    assert "Checking recent conversions in this browser" in content
    assert content.count("data-local-pending") >= 4
    assert "<noscript>" in content
    assert "<noscript>\n      <style>" not in content
    assert (
        "JavaScript is required to read browser-local saved places, saved pairs and recent history."
        in content
    )
