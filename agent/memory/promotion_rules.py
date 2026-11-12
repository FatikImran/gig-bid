def should_promote_style_edit(edit_count: int, consistent_pattern: bool) -> bool:
    if edit_count < 0:
        raise ValueError("edit_count cannot be negative")
    return edit_count >= 3 and consistent_pattern


def should_promote_outcome(outcome: str, marketplace_verified: bool, user_approved: bool) -> bool:
    if outcome not in {"won", "replied", "ignored", "lost"}:
        raise ValueError("Unsupported outcome label")
    return marketplace_verified and user_approved
