from app.security import hash_password, verify_password


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_password_hash_is_salted_differently_each_time():
    a = hash_password("same password")
    b = hash_password("same password")
    assert a != b
    assert verify_password("same password", a)
    assert verify_password("same password", b)


def test_seeded_users_have_working_credentials(db_session):
    from app.data.users_seed import USERS
    from app.models import User

    for entry in USERS:
        user = db_session.query(User).filter(User.username == entry["username"]).one()
        assert verify_password(entry["password"], user.password_hash)
        assert user.role == entry["role"]


def test_login_lockout_after_repeated_failures():
    from app.rate_limit import _failures, clear_failures, is_locked_out, record_failure

    username = "lockout-test-user"
    clear_failures(username)
    try:
        assert is_locked_out(username) is None
        for _ in range(5):
            record_failure(username)
        remaining = is_locked_out(username)
        assert remaining is not None
        assert 0 < remaining <= 15 * 60
    finally:
        clear_failures(username)
        _failures.pop(username, None)


def test_login_lockout_clears_on_success():
    from app.rate_limit import clear_failures, is_locked_out, record_failure

    username = "lockout-clear-user"
    clear_failures(username)
    try:
        for _ in range(5):
            record_failure(username)
        assert is_locked_out(username) is not None
        clear_failures(username)
        assert is_locked_out(username) is None
    finally:
        clear_failures(username)
