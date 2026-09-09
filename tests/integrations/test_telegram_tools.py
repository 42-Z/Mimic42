from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from telethon import functions, types

from mimic42.core.agent_runtime import _extract_incoming_text
from mimic42.integrations.telegram_tools import (
    CustomMarkdown,
    TelegramToolbox,
    build_telegram_langchain_tools,
    format_media_object,
    parse_media_id,
)


class FakeTelethonClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.requests: list[object] = []

    async def __call__(self, request: object) -> Any:
        self.requests.append(request)
        if isinstance(request, functions.users.GetFullUserRequest):
            full_user = MagicMock(spec=types.UserFull)
            full_user.id = 123
            full_user.about = "This is a bio"
            full_user.common_chats_count = 5

            user_obj = MagicMock(spec=types.User)
            user_obj.id = 123
            user_obj.first_name = "Ivan"
            user_obj.last_name = "Petrov"
            user_obj.username = "ivan_petrov"

            res = MagicMock(spec=types.users.UserFull)
            res.full_user = full_user
            res.chats = []
            res.users = [user_obj]
            return res
        elif isinstance(request, functions.channels.GetFullChannelRequest):
            full_chat = MagicMock(spec=types.ChannelFull)
            full_chat.about = "Group description"
            full_chat.participants_count = 100
            full_chat.admins_count = 5
            full_chat.linked_chat_id = 789

            chat_obj = MagicMock(spec=types.Channel)
            chat_obj.id = 456
            chat_obj.title = "Test Group"
            chat_obj.username = "test_group"

            res = MagicMock(spec=types.messages.ChatFull)
            res.full_chat = full_chat
            res.chats = [chat_obj]
            res.users = []
            return res
        elif isinstance(request, functions.channels.JoinChannelRequest):
            res = MagicMock(spec=types.Updates)
            res.updates = []
            res.chats = [request.channel]
            res.users = []
            return res
        elif isinstance(request, functions.channels.GetParticipantRequest):
            participant = MagicMock(spec=types.ChannelParticipantAdmin)
            participant.user_id = 123
            participant.title = "Moderator"

            res = MagicMock(spec=types.channels.ChannelParticipant)
            res.participant = participant
            res.chats = []
            res.users = []
            return res
        elif isinstance(request, functions.messages.GetCommonChatsRequest):
            chat = MagicMock(spec=types.Channel)
            chat.id = 789
            chat.title = "Common Group"
            chat.username = "common_group"

            res = MagicMock(spec=types.messages.Chats)
            res.chats = [chat]
            return res
        elif isinstance(request, functions.messages.GetAllStickersRequest):
            sticker_set = MagicMock(spec=types.StickerSet)
            sticker_set.id = 111
            sticker_set.access_hash = 222
            sticker_set.title = "Pepe"
            sticker_set.short_name = "pepe"
            sticker_set.count = 10

            res = MagicMock(spec=types.messages.AllStickers)
            res.hash = 0
            res.sets = [sticker_set]
            return res
        elif isinstance(request, functions.messages.GetStickerSetRequest):
            doc = MagicMock(spec=types.Document)
            doc.id = 333
            doc.access_hash = 444
            doc.file_reference = b"\x09"
            doc.dc_id = 1
            sticker_attr = MagicMock(spec=types.DocumentAttributeSticker)
            sticker_attr.alt = "🔥"
            sticker_attr.stickerset = MagicMock(spec=types.InputStickerSetEmpty)
            doc.attributes = [sticker_attr]

            res = MagicMock(spec=types.messages.StickerSet)
            res.documents = [doc]
            return res
        elif isinstance(request, functions.messages.SearchStickerSetsRequest):
            sticker_set = MagicMock(spec=types.StickerSet)
            sticker_set.id = 111
            sticker_set.access_hash = 222
            sticker_set.title = "Pepe"
            sticker_set.short_name = "pepe"
            sticker_set.count = 10

            res = MagicMock(spec=types.messages.FoundStickerSets)
            res.sets = [sticker_set]
            return res
        elif isinstance(request, functions.contacts.GetContactsRequest):
            user = MagicMock(spec=types.User)
            user.id = 123
            user.first_name = "Ivan"
            user.last_name = "Petrov"
            user.username = "ivan_petrov"
            user.phone = "12345"

            res = MagicMock(spec=types.contacts.Contacts)
            res.users = [user]
            return res
        elif isinstance(request, functions.messages.GetMessageReactionsListRequest):
            reaction = MagicMock(spec=types.MessagePeerReaction)
            reaction.peer_id = types.PeerUser(user_id=123)
            reaction.reaction = types.ReactionEmoji(emoticon="👍")

            res = MagicMock(spec=types.messages.MessageReactionsList)
            res.reactions = [reaction]
            return res
        elif isinstance(request, functions.messages.GetDialogFiltersRequest):
            filter_custom = MagicMock(spec=types.DialogFilter)
            filter_custom.id = 2
            filter_custom.title = MagicMock()
            filter_custom.title.text = "Work"
            filter_custom.emoticon = "💼"
            filter_custom.color = 1
            filter_custom.pinned_peers = [types.InputPeerUser(user_id=123, access_hash=0)]
            filter_custom.include_peers = [types.InputPeerChannel(channel_id=456, access_hash=0)]
            filter_custom.exclude_peers = []
            filter_custom.contacts = True
            filter_custom.non_contacts = False
            filter_custom.groups = True
            filter_custom.broadcasts = False
            filter_custom.bots = False
            filter_custom.exclude_muted = True
            filter_custom.exclude_read = False
            filter_custom.exclude_archived = True

            filter_default = MagicMock(spec=types.DialogFilterDefault)

            return [filter_custom, filter_default]
        elif isinstance(request, functions.messages.UpdateDialogFilterRequest):
            return True
        elif isinstance(request, functions.messages.GetBotCallbackAnswerRequest):
            res = MagicMock(spec=types.messages.BotCallbackAnswer)
            res.message = "Callback answered"
            res.alert = False
            res.url = None
            return res
        elif isinstance(request, functions.messages.GetInlineBotResultsRequest):
            inline_result = MagicMock(spec=types.BotInlineResult)
            inline_result.id = "result_1"
            inline_result.type = "article"
            inline_result.title = "Test Result"
            inline_result.description = "A test inline result"
            inline_result.url = "https://example.com/article"

            res = MagicMock(spec=types.messages.BotResults)
            res.query_id = 12345
            res.results = [inline_result]
            return res
        elif isinstance(request, functions.messages.SendInlineBotResultRequest):
            return True
        elif isinstance(request, functions.account.GetPrivacyRequest):
            privacy_rule = MagicMock(spec=types.PrivacyValueAllowContacts)
            res = MagicMock(spec=types.account.PrivacyRules)
            res.rules = [privacy_rule]
            res.chats = []
            res.users = []
            return res
        elif isinstance(request, functions.account.SetPrivacyRequest):
            return True
        elif isinstance(request, functions.account.GetGlobalPrivacySettingsRequest):
            settings = MagicMock(spec=types.GlobalPrivacySettings)
            settings.archive_and_mute_new_noncontact_peers = True
            settings.keep_archived_unmuted = True
            settings.keep_archived_folders = True
            settings.hide_read_marks = False
            settings.new_noncontact_peers_require_premium = False
            settings.display_gifts_button = True
            settings.noncontact_peers_paid_stars = None
            return settings
        elif isinstance(request, functions.account.SetGlobalPrivacySettingsRequest):
            return True
        elif isinstance(request, functions.account.GetContentSettingsRequest):
            settings = MagicMock(spec=types.account.ContentSettings)
            settings.sensitive_enabled = False
            settings.sensitive_can_change = True
            return settings
        elif isinstance(request, functions.account.SetContentSettingsRequest):
            return True
        return True

    async def get_entity(self, peer: Any) -> Any:
        self.calls.append(("get_entity", {"peer": peer}))
        if peer == "username":
            user = MagicMock(spec=types.User)
            user.id = 123
            user.first_name = "Ivan"
            user.last_name = "Petrov"
            user.username = "ivan_petrov"
            user.phone = "12345"
            user.bot = False
            user.status = MagicMock(spec=types.UserStatusOnline)
            return user
        elif peer == "group":
            channel = MagicMock(spec=types.Channel)
            channel.id = 456
            channel.title = "Test Group"
            channel.username = "test_group"
            channel.megagroup = True
            return channel
        elif peer == 789:
            channel = MagicMock(spec=types.Channel)
            channel.id = 789
            channel.title = "Discussion Group"
            channel.username = "discussion_group"
            channel.megagroup = True
            return channel
        user = MagicMock(spec=types.User)
        user.id = 123
        user.first_name = "Ivan"
        user.last_name = None
        user.username = None
        user.phone = None
        user.bot = False
        user.status = None
        return user

    async def get_input_entity(self, peer: Any) -> Any:
        self.calls.append(("get_input_entity", {"peer": peer}))
        return MagicMock(spec=types.InputPeerUser)

    async def get_messages(self, entity: Any, **kwargs: Any) -> Any:
        self.calls.append(("get_messages", {"entity": entity, "kwargs": kwargs}))
        ids = kwargs.get("ids")
        msg = MagicMock(spec=types.Message)
        msg.id = ids if isinstance(ids, int) else 777
        msg.text = "Mock message text"
        msg.media = None
        msg.reply_markup = None

        # Build reply_markup for button tests
        callback_btn = MagicMock(spec=types.KeyboardButtonCallback)
        callback_btn.text = "Yes"
        callback_btn.data = b"yes_data"

        url_btn = MagicMock(spec=types.KeyboardButtonUrl)
        url_btn.text = "Visit"
        url_btn.url = "https://example.com"

        reply_btn = MagicMock(spec=types.KeyboardButton)
        reply_btn.text = "Reply"

        row1 = MagicMock()
        row1.buttons = [callback_btn, url_btn]
        row2 = MagicMock()
        row2.buttons = [reply_btn]

        markup = MagicMock(spec=types.ReplyInlineMarkup)
        markup.rows = [row1, row2]
        msg.reply_markup = markup

        if ids == 999:
            return None
        return msg

    async def send_file(self, entity: Any, file: Any, **kwargs: Any) -> Any:
        self.calls.append(("send_file", {"entity": entity, "file": file, "kwargs": kwargs}))
        msg = MagicMock(spec=types.Message)
        msg.id = 999
        return msg

    async def send_message(self, entity: Any, message: str, **kwargs: Any) -> Any:
        self.calls.append(
            ("send_message", {"entity": entity, "message": message, "kwargs": kwargs})
        )
        msg = MagicMock(spec=types.Message)
        msg.id = 888
        return msg

    async def edit_message(self, entity: Any, message: Any, text: str, **kwargs: Any) -> Any:
        self.calls.append(
            ("edit_message", {"entity": entity, "message": message, "text": text, "kwargs": kwargs})
        )
        msg = MagicMock(spec=types.Message)
        msg.id = 777
        return msg

    async def delete_messages(self, entity: Any, message_ids: list[int], **kwargs: Any) -> Any:
        self.calls.append(
            ("delete_messages", {"entity": entity, "message_ids": message_ids, "kwargs": kwargs})
        )
        return True

    async def forward_messages(
        self, entity: Any, messages: list[int], from_peer: Any, **kwargs: Any
    ) -> Any:
        self.calls.append(
            (
                "forward_messages",
                {"entity": entity, "messages": messages, "from_peer": from_peer, "kwargs": kwargs},
            )
        )
        return True

    async def pin_message(self, entity: Any, message: Any, **kwargs: Any) -> Any:
        self.calls.append(("pin_message", {"entity": entity, "message": message, "kwargs": kwargs}))
        return True

    async def unpin_message(self, entity: Any, message: Any, **kwargs: Any) -> Any:
        self.calls.append(
            ("unpin_message", {"entity": entity, "message": message, "kwargs": kwargs})
        )
        return True

    async def delete_dialog(self, entity: Any, **kwargs: Any) -> Any:
        self.calls.append(("delete_dialog", {"entity": entity, "kwargs": kwargs}))
        return True

    async def edit_permissions(self, entity: Any, user: Any, **kwargs: Any) -> Any:
        self.calls.append(("edit_permissions", {"entity": entity, "user": user, "kwargs": kwargs}))
        return True

    async def edit_admin(self, entity: Any, user: Any, **kwargs: Any) -> Any:
        self.calls.append(("edit_admin", {"entity": entity, "user": user, "kwargs": kwargs}))
        return True

    async def kick_participant(self, entity: Any, user: Any) -> Any:
        self.calls.append(("kick_participant", {"entity": entity, "user": user}))
        return True

    async def upload_file(self, file: Any, **kwargs: Any) -> Any:
        self.calls.append(("upload_file", {"file": file, "kwargs": kwargs}))
        return MagicMock()

    async def download_media(self, message: Any, file: Any = None, **kwargs: Any) -> Any:
        self.calls.append(("download_media", {"message": message, "file": file, "kwargs": kwargs}))
        if file is bytes:
            return b"fake_image_data"
        return "fake_path"

    async def get_permissions(self, entity: Any, user: Any) -> Any:
        self.calls.append(("get_permissions", {"entity": entity, "user": user}))

        class FakePermissions:
            is_admin = True
            is_creator = False
            pin_messages = True
            delete_messages = True
            edit_messages = False
            invite_users = True
            ban_users = True
            change_info = False
            post_messages = False
            add_admins = False

        return FakePermissions()

    def action(self, entity: Any, action_obj: Any) -> Any:
        self.calls.append(("action", {"entity": entity, "action_obj": action_obj}))

        class AsyncContext:
            async def __aenter__(self) -> None:
                pass

            async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
                pass

        return AsyncContext()

    def iter_messages(self, entity: Any, **kwargs: Any) -> Any:
        self.calls.append(("iter_messages", {"entity": entity, "kwargs": kwargs}))

        async def gen() -> Any:
            msg = MagicMock(spec=types.Message)
            msg.id = 777
            msg.sender_id = 123
            msg.date = datetime.now()
            msg.text = "Mock message text"
            msg.media = None
            msg.reply_markup = None
            yield msg

        return gen()

    def iter_admin_log(self, entity: Any, **kwargs: Any) -> Any:
        self.calls.append(("iter_admin_log", {"entity": entity, "kwargs": kwargs}))

        async def gen() -> Any:
            event = MagicMock()
            event.id = 888
            event.date = datetime.now()
            event.user_id = 123
            event.action = MagicMock()
            event.action.stringify.return_value = "MockAction"
            yield event

        return gen()

    def iter_participants(self, entity: Any, **kwargs: Any) -> Any:
        self.calls.append(("iter_participants", {"entity": entity, "kwargs": kwargs}))

        async def gen() -> Any:
            user = MagicMock(spec=types.User)
            user.id = 123
            user.first_name = "Ivan"
            user.last_name = "Petrov"
            user.username = None
            user.bot = False

            participant = MagicMock(spec=types.ChannelParticipantAdmin)
            participant.title = "AdminTag"
            user.participant = participant
            yield user

        return gen()

    async def get_dialogs(self, limit: int = 20) -> list[Any]:
        self.calls.append(("get_dialogs", {"limit": limit}))
        dialog = MagicMock()
        dialog.id = 456
        dialog.title = "Test Group"
        dialog.unread_count = 0
        dialog.entity = MagicMock()
        dialog.entity.username = "test_group"
        return [dialog]


def test_custom_markdown_parser() -> None:
    text = "Hello [👍](emoji/123456) World"
    parsed, entities = CustomMarkdown.parse(text)

    assert parsed == "Hello 👍 World"
    assert len(entities) == 1
    assert isinstance(entities[0], types.MessageEntityCustomEmoji)
    assert entities[0].document_id == 123456

    # Test reverse (unparse)
    restored = CustomMarkdown.unparse(parsed, entities)
    assert restored == "Hello [👍](emoji/123456) World"


def test_format_media_object() -> None:
    photo = MagicMock(spec=types.Photo)
    photo.id = 123
    photo.access_hash = 456
    photo.file_reference = b"\x01\x02"
    photo.dc_id = 2

    media = MagicMock(spec=types.MessageMediaPhoto)
    media.photo = photo

    msg = MagicMock(spec=types.Message)
    msg.id = 1
    msg.media = media
    media_id = format_media_object(msg)
    assert media_id == "photo:123:456:0102:2"

    parsed = parse_media_id(media_id)
    assert parsed == ("photo", 123, 456, b"\x01\x02", 2)


def test_extract_incoming_text_media() -> None:
    photo = MagicMock(spec=types.Photo)
    photo.id = 123
    photo.access_hash = 456
    photo.file_reference = b"\x01\x02"
    photo.dc_id = 2

    media = MagicMock(spec=types.MessageMediaPhoto)
    media.photo = photo

    msg = MagicMock(spec=types.Message)
    msg.id = 1
    msg.media = media

    event = MagicMock()
    event.raw_text = "Look at this"
    event.text = "Look at this"
    event.message = msg

    extracted = _extract_incoming_text(event)
    assert "[Фото id=photo:123:456:0102:2]" in extracted
    assert "Look at this" in extracted


@pytest.mark.asyncio
async def test_get_profile() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    profile = await toolbox.get_profile("username")
    assert profile["id"] == 123
    assert profile["first_name"] == "Ivan"
    assert profile["bio"] == "This is a bio"
    assert profile["common_chats_count"] == 5


@pytest.mark.asyncio
async def test_get_chat_info() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    chat_info = await toolbox.get_chat_info("group")
    assert chat_info["id"] == 456
    assert chat_info["title"] == "Test Group"
    assert chat_info["about"] == "Group description"
    assert chat_info["participants_count"] == 100


@pytest.mark.asyncio
async def test_check_admin_permissions() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    perms = await toolbox.check_admin_permissions("group")
    assert perms["is_admin"] is True
    assert perms["can_pin_messages"] is True
    assert perms["can_edit_messages"] is False


@pytest.mark.asyncio
async def test_view_image() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    media_id = "photo:123:456:0102:2"
    result = await toolbox.view_image(media_id)
    assert len(result) == 1
    assert result[0]["type"] == "image_url"
    assert "data:image/jpeg;base64," in result[0]["image_url"]["url"]


@pytest.mark.asyncio
async def test_send_file() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    media_id = "photo:123:456:0102:2"
    result = await toolbox.send_file("username", media_id, caption="Hello")
    assert result["success"] is True
    assert result["message_id"] == 999
    assert len(client.calls) == 2  # get_input_entity, send_file


@pytest.mark.asyncio
async def test_get_common_chats() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    chats = await toolbox.get_common_chats("username")
    assert len(chats) == 1
    assert chats[0]["id"] == 789
    assert chats[0]["title"] == "Common Group"


@pytest.mark.asyncio
async def test_get_chat_members() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    members = await toolbox.get_chat_members("group")
    assert len(members) == 1
    assert members[0]["id"] == 123
    assert members[0]["first_name"] == "Ivan"
    assert members[0]["title"] == "AdminTag"


@pytest.mark.asyncio
async def test_tools_exposed_in_langchain() -> None:
    client = FakeTelethonClient()
    tools = build_telegram_langchain_tools(client)

    assert len(tools) == 91
    tool_names = [t.name for t in tools]
    assert "send_text_message" in tool_names
    assert "view_image" in tool_names
    assert "check_admin_permissions" in tool_names
    assert "transcribe_voice_note" in tool_names
    assert "read_document_file" in tool_names
    assert "set_wakeup_timer" in tool_names
    assert "mute_chat" in tool_names
    assert "unmute_chat" in tool_names
    assert "send_location" in tool_names
    assert "send_venue" in tool_names
    assert "search_location" in tool_names
    assert "get_chat_folders" in tool_names
    assert "create_or_update_chat_folder" in tool_names
    assert "delete_chat_folder" in tool_names
    assert "get_privacy_settings" in tool_names
    assert "set_privacy_settings" in tool_names
    assert "get_global_settings" in tool_names
    assert "set_global_settings" in tool_names
    assert "get_content_settings" in tool_names
    assert "set_content_settings" in tool_names


@pytest.mark.asyncio
async def test_extract_incoming_text_extended_media() -> None:
    # 1. Test Sticker with pack name
    sticker = MagicMock(spec=types.Document)
    sticker.id = 123
    sticker.access_hash = 456
    sticker.file_reference = b"\x01\x02"
    sticker.dc_id = 2

    sticker_attr = MagicMock(spec=types.DocumentAttributeSticker)
    sticker_attr.alt = "👍"
    sticker_attr.stickerset = MagicMock(spec=types.InputStickerSetShortName)
    sticker_attr.stickerset.short_name = "pepe_pack"
    sticker.attributes = [sticker_attr]

    media_sticker = MagicMock(spec=types.MessageMediaDocument)
    media_sticker.document = sticker

    msg_sticker = MagicMock(spec=types.Message)
    msg_sticker.id = 1
    msg_sticker.media = media_sticker

    event_sticker = MagicMock()
    event_sticker.raw_text = "Sticker message"
    event_sticker.text = "Sticker message"
    event_sticker.message = msg_sticker

    text_sticker = _extract_incoming_text(event_sticker)
    assert "[Стикер 👍 id=sticker:123:456:0102:2:👍:pepe_pack пак=pepe_pack]" in text_sticker

    # 2. Test Voice note
    voice = MagicMock(spec=types.Document)
    voice.id = 789
    voice.access_hash = 1011
    voice.file_reference = b"\x03\x04"
    voice.dc_id = 3

    voice_attr = MagicMock(spec=types.DocumentAttributeAudio)
    voice_attr.voice = True
    voice.attributes = [voice_attr]

    media_voice = MagicMock(spec=types.MessageMediaDocument)
    media_voice.document = voice

    msg_voice = MagicMock(spec=types.Message)
    msg_voice.id = 2
    msg_voice.media = media_voice

    event_voice = MagicMock()
    event_voice.raw_text = ""
    event_voice.text = ""
    event_voice.message = msg_voice

    text_voice = _extract_incoming_text(event_voice)
    assert "[Голосовое сообщение id=voice:789:1011:0304:3]" in text_voice

    # 3. Test Video note
    video = MagicMock(spec=types.Document)
    video.id = 1213
    video.access_hash = 1415
    video.file_reference = b"\x05\x06"
    video.dc_id = 4

    video_attr = MagicMock(spec=types.DocumentAttributeVideo)
    video_attr.round_message = True
    video.attributes = [video_attr]

    media_video = MagicMock(spec=types.MessageMediaDocument)
    media_video.document = video

    msg_video = MagicMock(spec=types.Message)
    msg_video.id = 3
    msg_video.media = media_video

    event_video = MagicMock()
    event_video.raw_text = ""
    event_video.text = ""
    event_video.message = msg_video

    text_video = _extract_incoming_text(event_video)
    assert "[Видеосообщение id=round:1213:1415:0506:4]" in text_video

    # 4. Test File with name
    doc_file = MagicMock(spec=types.Document)
    doc_file.id = 1617
    doc_file.access_hash = 1819
    doc_file.file_reference = b"\x07\x08"
    doc_file.dc_id = 5

    filename_attr = MagicMock(spec=types.DocumentAttributeFilename)
    filename_attr.file_name = "test_doc.pdf"
    doc_file.attributes = [filename_attr]

    media_doc = MagicMock(spec=types.MessageMediaDocument)
    media_doc.document = doc_file

    msg_doc = MagicMock(spec=types.Message)
    msg_doc.id = 4
    msg_doc.media = media_doc

    event_doc = MagicMock()
    event_doc.raw_text = "Doc text"
    event_doc.text = "Doc text"
    event_doc.message = msg_doc

    text_doc = _extract_incoming_text(event_doc)
    assert "[Файл name=test_doc.pdf id=doc:1617:1819:0708:5:test_doc.pdf]" in text_doc


@pytest.mark.asyncio
async def test_member_tags_caching() -> None:
    from uuid import uuid4

    from mimic42.core.agent_runtime import (
        AgentRuntimeConfig,
        AgentRuntimeState,
        MimicAgentRuntime,
    )

    config = AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_session_name="test_session",
        telegram_api_id=123,
        telegram_api_hash="abc",
        system_prompt="You are an agent",
    )

    client = FakeTelethonClient()

    langchain = MagicMock()

    async def mock_ainvoke(input_data: dict[str, object]) -> Any:
        res = MagicMock()
        res.content = "Ok"
        return res

    langchain.ainvoke = mock_ainvoke

    runtime = MimicAgentRuntime(
        config=config,
        telegram_client=client,
        langchain_agent=langchain,
    )
    runtime._state = AgentRuntimeState.RUNNING

    event = MagicMock()
    event.is_group = True
    event.is_channel = True
    event.chat_id = 999
    event.sender_id = 888
    event.id = 1
    event.raw_text = "Hello"
    event.text = "Hello"
    event.message = None
    event.client = client

    sender = MagicMock(spec=types.User)
    sender.first_name = "Alice"
    sender.last_name = None
    sender.id = 888

    async def get_sender() -> Any:
        return sender

    event.get_sender = get_sender

    async def get_chat() -> Any:
        return "999"

    event.get_chat = get_chat

    # 1. Trigger handler (should fetch from Telegram and cache)
    await runtime._handle_incoming_message(event)
    get_participant_requests = [
        r for r in client.requests if isinstance(r, functions.channels.GetParticipantRequest)
    ]
    assert len(get_participant_requests) == 1

    # 2. Trigger handler again (should hit cache, no new calls)
    await runtime._handle_incoming_message(event)
    get_participant_requests_2 = [
        r for r in client.requests if isinstance(r, functions.channels.GetParticipantRequest)
    ]
    assert len(get_participant_requests_2) == 1

    # Verify cached title was used in trigger
    assert (999, 888) in runtime._member_tag_cache
    cached_title, _ = runtime._member_tag_cache[(999, 888)]
    assert cached_title == "Moderator"


@pytest.mark.asyncio
async def test_remaining_message_tools() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    # send_text_message
    res_send = await toolbox.send_text_message("group", "Hello")
    assert res_send["success"] is True
    assert res_send["message_id"] == 888

    # edit_text_message
    res = await toolbox.edit_text_message("group", 123, "New text")
    assert res["success"] is True
    assert res["message_id"] == 777

    # delete_messages
    res = await toolbox.delete_messages("group", [123, 456])
    assert res["success"] is True

    # forward_messages
    res = await toolbox.forward_messages("from_group", "to_group", [123])
    assert res["success"] is True

    # pin_message
    res = await toolbox.pin_message("group", 123)
    assert res["success"] is True

    # unpin_message
    res = await toolbox.unpin_message("group", 123)
    assert res["success"] is True

    # unpin_all_messages
    res = await toolbox.unpin_all_messages("group")
    assert res["success"] is True

    # send_chat_action
    res = await toolbox.send_chat_action("group", "record_audio")
    assert res["success"] is True

    # send_reaction
    res = await toolbox.send_reaction("group", 123, "👍")
    assert res["success"] is True

    # get_message_reactions
    res = await toolbox.get_message_reactions("group", 123)
    assert len(res["reactions"]) == 1
    assert res["reactions"][0]["emoji"] == "👍"

    # mark_chat_as_read
    res = await toolbox.mark_chat_as_read("group", 123)
    assert res["success"] is True

    # get_messages
    msgs = await toolbox.get_messages("group", limit=5)
    assert len(msgs) == 1
    assert msgs[0]["id"] == 777


@pytest.mark.asyncio
async def test_remaining_navigation_and_dialog_tools() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    # get_dialogs
    res = await toolbox.get_dialogs(limit=5)
    assert len(res) == 1
    assert res[0]["id"] == 456

    # search_messages
    res = await toolbox.search_messages("group", "query")
    assert len(res) == 1
    assert res[0]["id"] == 777

    # delete_dialog
    res = await toolbox.delete_dialog("group")
    assert res["success"] is True

    # archive_dialogs
    res = await toolbox.archive_dialogs(["group"])
    assert res["success"] is True

    # unarchive_dialogs
    res = await toolbox.unarchive_dialogs(["group"])
    assert res["success"] is True


@pytest.mark.asyncio
async def test_remaining_media_tools() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    # set_profile_photo
    res = await toolbox.set_profile_photo("photo:123:456:0102:2")
    assert res["success"] is True

    # send_voice_note
    res = await toolbox.send_voice_note("group", "voice:123:456:0102:2")
    assert res["success"] is True
    assert res["message_id"] == 999

    # send_video_note
    res = await toolbox.send_video_note("group", "round:123:456:0102:2")
    assert res["success"] is True
    assert res["message_id"] == 999


@pytest.mark.asyncio
async def test_remaining_sticker_tools() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    # get_sticker_sets
    res = await toolbox.get_sticker_sets()
    assert len(res) == 1
    assert res[0]["short_name"] == "pepe"

    # get_stickers_in_set
    res = await toolbox.get_stickers_in_set("pepe")
    assert len(res) == 1
    assert "sticker:333:444:09:1" in res[0]["media_id"]

    # search_sticker_sets
    res = await toolbox.search_sticker_sets("pepe")
    assert len(res) == 1
    assert res[0]["short_name"] == "pepe"

    # install_sticker_set
    res = await toolbox.install_sticker_set("pepe")
    assert res["success"] is True

    # uninstall_sticker_set
    res = await toolbox.uninstall_sticker_set("pepe")
    assert res["success"] is True

    # send_sticker
    res = await toolbox.send_sticker("group", "sticker:123:456:0102:2:emoji:pack")
    assert res["success"] is True


@pytest.mark.asyncio
async def test_remaining_profile_and_contact_tools() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    # update_profile_info
    res = await toolbox.update_profile_info(first_name="NewName", bio="NewBio")
    assert res["success"] is True

    # update_username
    res = await toolbox.update_username("new_username")
    assert res["success"] is True

    # add_contact
    res = await toolbox.add_contact("79991234567", "Alice")
    assert res["success"] is True

    # delete_contact
    res = await toolbox.delete_contact("username")
    assert res["success"] is True

    # get_contacts
    res = await toolbox.get_contacts()
    assert len(res) == 1
    assert res[0]["username"] == "ivan_petrov"


@pytest.mark.asyncio
async def test_remaining_group_and_channel_tools() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    # create_group
    res = await toolbox.create_group("GroupTitle", ["username"])
    assert res["success"] is True

    # create_channel
    res = await toolbox.create_channel("ChannelTitle")
    assert res["success"] is True

    # invite_to_channel
    res = await toolbox.invite_to_channel("channel", ["username"])
    assert res["success"] is True

    # kick_chat_member
    res = await toolbox.kick_chat_member("group", "username")
    assert res["success"] is True

    # ban_chat_member
    res = await toolbox.ban_chat_member("group", "username")
    assert res["success"] is True

    # restrict_chat_member
    res = await toolbox.restrict_chat_member("group", "username")
    assert res["success"] is True

    # promote_chat_member
    res = await toolbox.promote_chat_member("group", "username", title="SuperMod")
    assert res["success"] is True

    # get_chat_admin_log
    res = await toolbox.get_chat_admin_log("group")
    assert len(res) == 1
    assert res[0]["action"] == "MockAction"

    # join_channel
    res = await toolbox.join_channel("channel")
    assert res["success"] is True

    # send_poll
    res = await toolbox.send_poll("group", "Q?", ["Yes", "No"])
    assert res["success"] is True
    assert res["message_id"] == 999


@pytest.mark.asyncio
async def test_transcribe_and_read_file_tools() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    # Test transcribe_voice_note
    res_trans = await toolbox.transcribe_voice_note("voice:123:456:0102:2")
    assert res_trans["success"] is True
    assert "расшифровка" in res_trans["transcription"]

    # Test read_document_file
    res_read = await toolbox.read_document_file("doc:123:456:0102:2:info.txt")
    assert res_read["success"] is True
    assert "содержимое" in res_read["content"]


@pytest.mark.asyncio
async def test_mute_and_unmute_tools() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    # Test mute_chat indefinite
    res = await toolbox.mute_chat("group")
    assert res["success"] is True
    assert len(client.requests) == 1
    req = client.requests[0]
    assert isinstance(req, functions.account.UpdateNotifySettingsRequest)
    assert req.settings.silent is True
    assert req.settings.mute_until is not None

    # Test mute_chat with custom duration
    res_dur = await toolbox.mute_chat("group", duration_hours=2)
    assert res_dur["success"] is True
    assert len(client.requests) == 2
    req_dur = client.requests[1]
    assert req_dur.settings.silent is True

    # Test unmute_chat
    res_unmute = await toolbox.unmute_chat("group")
    assert res_unmute["success"] is True
    assert len(client.requests) == 3
    req_unmute = client.requests[2]
    assert req_unmute.settings.silent is False
    assert req_unmute.settings.mute_until == datetime(1970, 1, 1)


@pytest.mark.asyncio
async def test_location_and_venue_tools() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    # Test send_location
    res = await toolbox.send_location("group", latitude=59.9398, longitude=30.3146)
    assert res["success"] is True
    assert res["message_id"] == 999

    # Assert send_file calls
    send_file_calls = [c for c in client.calls if c[0] == "send_file"]
    assert len(send_file_calls) == 1
    call_args = send_file_calls[0][1]
    assert isinstance(call_args["file"], types.InputMediaGeoPoint)
    assert call_args["file"].geo_point.lat == 59.9398
    assert call_args["file"].geo_point.long == 30.3146

    # Test send_venue
    res_venue = await toolbox.send_venue(
        "group",
        latitude=48.8584,
        longitude=2.2945,
        title="Eiffel Tower",
        address="Champ de Mars, Paris",
    )
    assert res_venue["success"] is True
    assert res_venue["message_id"] == 999

    send_file_calls_updated = [c for c in client.calls if c[0] == "send_file"]
    assert len(send_file_calls_updated) == 2
    call_args_venue = send_file_calls_updated[1][1]
    assert isinstance(call_args_venue["file"], types.InputMediaVenue)
    assert call_args_venue["file"].geo_point.lat == 48.8584
    assert call_args_venue["file"].geo_point.long == 2.2945
    assert call_args_venue["file"].title == "Eiffel Tower"
    assert call_args_venue["file"].address == "Champ de Mars, Paris"


@pytest.mark.asyncio
async def test_search_location_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    class FakeResponse:
        def __init__(self) -> None:
            self.data = json.dumps(
                {
                    "candidates": [
                        {
                            "address": "Eiffel Tower, Paris, France",
                            "location": {"x": 2.2945, "y": 48.8584},
                        }
                    ]
                }
            ).encode("utf-8")

        def read(self) -> bytes:
            return self.data

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

    def mock_urlopen(*args: Any, **kwargs: Any) -> FakeResponse:
        return FakeResponse()

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    res = await toolbox.search_location("Eiffel Tower")
    assert res["success"] is True
    assert res["latitude"] == 48.8584
    assert res["longitude"] == 2.2945
    assert res["address"] == "Eiffel Tower, Paris, France"


@pytest.mark.asyncio
async def test_chat_folder_tools() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    # 1. Test get_chat_folders
    folders = await toolbox.get_chat_folders()
    assert len(folders) == 2

    f_custom = [f for f in folders if f.get("id") == 2][0]
    assert f_custom["title"] == "Work"
    assert f_custom["emoticon"] == "💼"
    assert f_custom["color"] == 1
    assert f_custom["contacts"] is True
    assert f_custom["groups"] is True
    assert f_custom["exclude_muted"] is True
    assert len(f_custom["pinned_peers"]) == 1
    assert f_custom["pinned_peers"][0]["type"] == "user"
    assert f_custom["pinned_peers"][0]["id"] == 123
    assert len(f_custom["include_peers"]) == 1
    assert f_custom["include_peers"][0]["type"] == "channel"
    assert f_custom["include_peers"][0]["id"] == 456

    f_default = [f for f in folders if f.get("id") == 0][0]
    assert f_default["title"] == "All Chats"
    assert f_default["type"] == "default"

    # 2. Test create_or_update_chat_folder
    res_create = await toolbox.create_or_update_chat_folder(
        folder_id=3,
        title="Friends",
        emoticon="👥",
        color=2,
        pinned_peers=["username"],
        include_peers=["group"],
        contacts=True,
    )
    assert res_create["success"] is True

    update_reqs = [
        r for r in client.requests if isinstance(r, functions.messages.UpdateDialogFilterRequest)
    ]
    assert len(update_reqs) == 1
    req = update_reqs[0]
    assert req.id == 3
    assert req.filter.title == "Friends"
    assert req.filter.emoticon == "👥"
    assert req.filter.color == 2
    assert req.filter.contacts is True
    assert len(req.filter.pinned_peers) == 1
    assert len(req.filter.include_peers) == 1

    # 3. Test delete_chat_folder
    res_delete = await toolbox.delete_chat_folder(folder_id=3)
    assert res_delete["success"] is True

    update_reqs_updated = [
        r for r in client.requests if isinstance(r, functions.messages.UpdateDialogFilterRequest)
    ]
    assert len(update_reqs_updated) == 2
    req_del = update_reqs_updated[1]
    assert req_del.id == 3
    assert req_del.filter is None


@pytest.mark.asyncio
async def test_bot_interaction_tools() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    # get_message_buttons
    res = await toolbox.get_message_buttons("group", 777)
    assert "buttons" in res
    assert len(res["buttons"]) == 3
    assert res["buttons"][0]["text"] == "Yes"
    assert res["buttons"][0]["type"] != ""
    assert res["buttons"][0]["data"] == "yes_data"
    assert res["buttons"][1]["url"] == "https://example.com"
    assert res["buttons"][2]["type"] != ""

    # get_message_buttons — no buttons
    res_empty = await toolbox.get_message_buttons("group", 999)
    assert res_empty["buttons"] == []

    # click_inline_button by button_data
    res_click = await toolbox.click_inline_button("group", 777, button_data="yes_data")
    assert res_click["success"] is True
    assert res_click["message"] == "Callback answered"

    # click_inline_button by button_index
    res_click_idx = await toolbox.click_inline_button("group", 777, button_index=0)
    assert res_click_idx["success"] is True

    # click_inline_button invalid index
    res_click_bad = await toolbox.click_inline_button("group", 777, button_index=10)
    assert res_click_bad["success"] is False
    assert "Invalid button index" in res_click_bad["error"]

    # click_reply_keyboard_button
    res_reply = await toolbox.click_reply_keyboard_button("group", "Reply")
    assert res_reply["success"] is True
    assert res_reply["message_id"] == 888

    # query_inline_bot
    res_inline = await toolbox.query_inline_bot("@testbot", "hello query")
    assert "error" not in res_inline
    assert res_inline["query_id"] == 12345
    assert len(res_inline["results"]) == 1
    assert res_inline["results"][0]["id"] == "result_1"

    # send_inline_bot_result
    res_send = await toolbox.send_inline_bot_result("group", 12345, "result_1")
    assert res_send["success"] is True

    # start_bot without parameter
    res_start = await toolbox.start_bot("@testbot")
    assert res_start["success"] is True
    assert res_start["message_id"] == 888
    send_calls = [c for c in client.calls if c[0] == "send_message"]
    assert send_calls[-1][1]["message"] == "/start"

    # start_bot with parameter
    res_start_param = await toolbox.start_bot("@testbot", parameter="ref123", peer="group")
    assert res_start_param["success"] is True
    send_calls = [c for c in client.calls if c[0] == "send_message"]
    assert send_calls[-1][1]["message"] == "/start ref123"


@pytest.mark.asyncio
async def test_privacy_and_account_settings_tools() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    # get_privacy_settings
    res = await toolbox.get_privacy_settings("status_timestamp")
    assert res["key"] == "status_timestamp"
    assert res["rules"] == ["allow_contacts"]

    # set_privacy_settings
    res_set = await toolbox.set_privacy_settings(
        key="phone_number",
        rule="disallow_all",
        allowed_users=["username"],
    )
    assert res_set["success"] is True
    set_reqs = [r for r in client.requests if isinstance(r, functions.account.SetPrivacyRequest)]
    assert len(set_reqs) == 1
    req = set_reqs[0]
    assert isinstance(req.key, types.InputPrivacyKeyPhoneNumber)
    assert len(req.rules) == 2  # disallow_all + allow_users exception

    # get_global_settings
    res_global = await toolbox.get_global_settings()
    assert res_global["archive_and_mute_new_noncontact_peers"] is True
    assert res_global["hide_read_marks"] is False

    # set_global_settings
    res_set_global = await toolbox.set_global_settings(
        hide_read_marks=True,
        archive_and_mute_new_noncontact_peers=False,
    )
    assert res_set_global["success"] is True
    global_reqs = [
        r
        for r in client.requests
        if isinstance(r, functions.account.SetGlobalPrivacySettingsRequest)
    ]
    assert len(global_reqs) == 1
    assert global_reqs[0].settings.hide_read_marks is True
    assert global_reqs[0].settings.archive_and_mute_new_noncontact_peers is False

    # get_content_settings
    res_content = await toolbox.get_content_settings()
    assert res_content["sensitive_enabled"] is False
    assert res_content["sensitive_can_change"] is True

    # set_content_settings
    res_set_content = await toolbox.set_content_settings(sensitive_enabled=True)
    assert res_set_content["success"] is True
    content_reqs = [
        r for r in client.requests if isinstance(r, functions.account.SetContentSettingsRequest)
    ]
    assert len(content_reqs) == 1
    assert content_reqs[0].sensitive_enabled is True


@pytest.mark.asyncio
async def test_join_channel_discussion() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    result = await toolbox.join_channel_discussion("group")
    assert result["success"] is True
    assert result["linked_chat_id"] == 789
    assert result["title"] == "Discussion Group"
    assert result["username"] == "discussion_group"
    assert result["is_group"] is True

    join_reqs = [r for r in client.requests if isinstance(r, functions.channels.JoinChannelRequest)]
    assert len(join_reqs) == 1


class FakeTelethonClientNoLinkedChat(FakeTelethonClient):
    async def __call__(self, request: object) -> Any:
        if isinstance(request, functions.channels.GetFullChannelRequest):
            full_chat = MagicMock(spec=types.ChannelFull)
            full_chat.about = "Group description"
            full_chat.participants_count = 100
            full_chat.admins_count = 5
            full_chat.linked_chat_id = None

            chat_obj = MagicMock(spec=types.Channel)
            chat_obj.id = 456
            chat_obj.title = "Test Group"
            chat_obj.username = "test_group"

            res = MagicMock(spec=types.messages.ChatFull)
            res.full_chat = full_chat
            res.chats = [chat_obj]
            res.users = []
            return res
        return await super().__call__(request)


@pytest.mark.asyncio
async def test_join_channel_discussion_no_linked_chat() -> None:
    client = FakeTelethonClientNoLinkedChat()
    toolbox = TelegramToolbox(client)

    result = await toolbox.join_channel_discussion("group")
    assert result == {"error": "This channel has no linked discussion group"}


@pytest.mark.asyncio
async def test_get_discussion_messages() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    messages = await toolbox.get_discussion_messages("group", 42, limit=10)
    assert len(messages) == 1
    assert messages[0]["id"] == 777
    assert messages[0]["text"] == "Mock message text"

    iter_calls = [c for c in client.calls if c[0] == "iter_messages"]
    assert len(iter_calls) == 1
    assert iter_calls[0][1]["kwargs"]["reply_to"] == 42
    assert iter_calls[0][1]["kwargs"]["limit"] == 10


@pytest.mark.asyncio
async def test_send_text_message_as_comment() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    result = await toolbox.send_text_message("channel", "Nice post", comment_to_msg_id=42)
    assert result["success"] is True

    send_calls = [c for c in client.calls if c[0] == "send_message"]
    assert len(send_calls) == 1
    assert send_calls[0][1]["kwargs"]["comment_to"] == 42
    assert send_calls[0][1]["kwargs"]["reply_to"] is None


@pytest.mark.asyncio
async def test_send_text_message_without_comment() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    await toolbox.send_text_message("group", "Hello", reply_to_msg_id=7)

    send_calls = [c for c in client.calls if c[0] == "send_message"]
    assert send_calls[0][1]["kwargs"]["comment_to"] is None
    assert send_calls[0][1]["kwargs"]["reply_to"] == 7


@pytest.mark.asyncio
async def test_send_text_message_comment_respects_cooldown() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    first = await toolbox.send_text_message("channel", "Nice post", comment_to_msg_id=42)
    assert first["success"] is True

    second = await toolbox.send_text_message("channel", "Another one", comment_to_msg_id=43)
    assert second["success"] is False
    assert "Cooldown" in second["error"]

    send_calls = [c for c in client.calls if c[0] == "send_message"]
    assert len(send_calls) == 1


@pytest.mark.asyncio
async def test_send_media_as_comment() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    media_id = "photo:123:456:0102:2"
    res_media = await toolbox.send_file("channel", media_id, comment_to_msg_id=42)
    assert res_media["success"] is True

    res_url = await toolbox.send_file(
        "channel", "https://example.com/pic.jpg", comment_to_msg_id=42
    )
    assert res_url["success"] is True

    res_sticker = await toolbox.send_sticker(
        "channel", "sticker:123:456:0102:2:emoji:pack", comment_to_msg_id=42
    )
    assert res_sticker["success"] is True

    res_voice = await toolbox.send_voice_note("channel", media_id, comment_to_msg_id=42)
    assert res_voice["success"] is True

    res_round = await toolbox.send_video_note("channel", media_id, comment_to_msg_id=42)
    assert res_round["success"] is True

    send_file_calls = [c for c in client.calls if c[0] == "send_file"]
    assert len(send_file_calls) == 5
    assert all(call[1]["kwargs"]["comment_to"] == 42 for call in send_file_calls)


@pytest.mark.asyncio
async def test_send_file_without_comment() -> None:
    client = FakeTelethonClient()
    toolbox = TelegramToolbox(client)

    await toolbox.send_file("username", "photo:123:456:0102:2", caption="Hello")

    send_file_calls = [c for c in client.calls if c[0] == "send_file"]
    assert send_file_calls[0][1]["kwargs"]["comment_to"] is None
