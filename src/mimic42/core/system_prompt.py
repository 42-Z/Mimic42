from __future__ import annotations

from dataclasses import dataclass

TOOL_INSTRUCTIONS_ANCHOR = "{{tool_instructions}}"


@dataclass(frozen=True)
class ToolPromptSection:
    required_names: frozenset[str]
    text: str


TOOL_PROMPT_SECTIONS = (
    ToolPromptSection(
        frozenset({"get_chat_info"}),
        "Перед первым действием в незнакомом канале, группе или у бота осмотрись через "
        "get_chat_info: так ты узнаешь правила и ограничения чата.",
    ),
    ToolPromptSection(
        frozenset({"get_messages"}),
        "Перед действием в незнакомом чате прочитай последние сообщения через get_messages. "
        "В истории могут быть правила и проверка для новичков.",
    ),
    ToolPromptSection(
        frozenset({"view_image"}),
        "Если в сообщении есть маркер [Фото id=...], а его содержимое важно "
        "(картинка-загадка, капча, скриншот), открой его через view_image. "
        "Прежде чем говорить, что на стикере, открой его через view_image по id из "
        "маркера и опирайся только на увиденное.",
    ),
    ToolPromptSection(
        frozenset({"get_message_buttons", "click_inline_button"}),
        "Если бот просит пройти проверку, реши её условие, затем через "
        "get_message_buttons найди кнопку с подходящим значением и нажми "
        "click_inline_button, скопировав её data. Не нажимай кнопки наугад: неверная "
        "попытка на капче может стоить доступа к чату.",
    ),
    ToolPromptSection(
        frozenset({"view_image", "get_message_buttons", "click_inline_button"}),
        "Если у проверки есть фото, сначала просмотри его через view_image и реши "
        "пример или вопрос с картинки, а уже затем выбирай кнопку.",
    ),
    ToolPromptSection(
        frozenset({"view_image", "send_sticker"}),
        "Если отвечаешь стикером, сначала посмотри, что на нём изображено, и только "
        "потом отправляй.",
    ),
    ToolPromptSection(
        frozenset({"delete_messages"}),
        "Удалять чужие сообщения через delete_messages можно только с соответствующими "
        "правами Telegram. Не пытайся делать это без них.",
    ),
    ToolPromptSection(
        frozenset({"pin_message"}),
        "Закрепление через pin_message требует соответствующих прав Telegram. "
        "Не пытайся закреплять сообщения без них.",
    ),
    ToolPromptSection(
        frozenset({"unpin_message"}),
        "Снятие закрепления через unpin_message требует соответствующих прав Telegram. "
        "Не пытайся снимать закрепление без них.",
    ),
    ToolPromptSection(
        frozenset({"send_text_message"}),
        "Инструмент send_text_message нужен только для отправки дополнительных "
        "сообщений. Если хочешь просто ответить человеку, не используй его, иначе "
        "получится несколько сообщений подряд.",
    ),
    ToolPromptSection(
        frozenset({"get_chat_info"}),
        "Перед комментарием к посту вызови get_chat_info для канала. В поле discussion "
        "видно, есть ли обсуждение, вступил ли ты в него (joined) и нужно ли вступать "
        "для комментария (join_required_to_comment). Если обсуждения нет, написать "
        "под постом нельзя.",
    ),
    ToolPromptSection(
        frozenset({"join_channel_discussion"}),
        "Если для комментария требуется вступить в обсуждение, вызови "
        "join_channel_discussion и прочитай его ответ целиком. В verification_messages "
        "лежат капча или правила для новичков. Пока проверка не пройдена, писать в "
        "группу нельзя.",
    ),
    ToolPromptSection(
        frozenset({"join_channel", "join_channel_discussion"}),
        "Вступление в сам канал через join_channel не пускает в обсуждение. "
        "Обсуждение канала это отдельная группа.",
    ),
    ToolPromptSection(
        frozenset({"join_channel"}),
        "Если нужно общаться в чате, вступи в него через join_channel, чтобы приходили "
        "уведомления о новых событиях.",
    ),
    ToolPromptSection(
        frozenset({"set_wakeup_timer"}),
        "Ты можешь создавать отложенные события через set_wakeup_timer, если "
        "планируешь заняться чем-то позже. Для длительной задачи (например, "
        "периодически общаться в комментариях) используй set_wakeup_timer. Без него "
        "с последним действием ты останавливаешься до следующего входящего триггера.",
    ),
)

COMMENT_SENDERS = (
    "send_text_message",
    "send_file",
    "send_voice_note",
    "send_video_note",
    "send_sticker",
)
MESSAGE_SENDERS = (
    *COMMENT_SENDERS,
    "forward_messages",
    "send_poll",
    "send_inline_bot_result",
    "send_location",
    "send_venue",
)


def render_system_prompt(
    base_prompt: str, *, available_names: frozenset[str], name: str, soul: str
) -> str:
    sections = [
        section.text
        for section in TOOL_PROMPT_SECTIONS
        if section.required_names <= available_names
    ]
    comment_senders = [sender for sender in COMMENT_SENDERS if sender in available_names]
    if comment_senders:
        sections.append(
            "Под постом канала нельзя ответить обычной отправкой в сам канал. "
            "Чтобы оставить комментарий, укажи ID поста в comment_to_msg_id, а в peer "
            "сам канал. Комментарий уходит в группу обсуждения. ID поста бери из "
            "самого канала, а не из другого чата. Доступные отправители комментариев: "
            + ", ".join(comment_senders)
            + "."
        )
    senders = [sender for sender in MESSAGE_SENDERS if sender in available_names]
    if senders:
        sections.append(
            "Если реплику уже отправил инструментом ("
            + ", ".join(senders)
            + "), в этом ходе верни send_any_message = false, а text оставь пустым. "
            "Иначе человек получит её дважды."
        )
    prompt = base_prompt.replace(TOOL_INSTRUCTIONS_ANCHOR, "\n\n".join(sections))
    return prompt.replace("{{name}}", name).replace("{{soul}}", soul)
