# Proof AP-712

Real MCP tool calls (tool functions invoked as the bot "proof-bot" against the test Postgres):

```
list_avatar_choices -> {'robot_styles': [{'value': 'bot:0', 'label': 'Classic'}, ... {'value': 'bot:5', 'label': 'Friendly'}], 'accepted': {'image_link': 'https:// link, max 1000 characters', 'image_data_url': 'data:image/(png|jpeg|webp|gif);base64,..., max 200 KB'}, 'max_image_kb': 200, 'current': ''}
update_profile(avatar_url='bot:2', verbose=True) -> bot:2
oversized image refused -> That image is too big. Allowed pictures: empty (default), a robot style like 'bot:0' (0 to 5), an https:// image link up to 1000 characters, or a small png/jpeg/webp/gif image as a base64 data URL up to 200 KB.
current after refusal -> bot:2
```

Tests: `python -m pytest backend/tests/test_profile_avatar.py backend/tests/test_mcp_write_responses.py -q` -> passed (ruff clean).
Note: frontend robot list (`bot:<n>` rendering) belongs to the separate bot-pictures task; not present in this branch.
