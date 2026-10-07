import type { ToolGroup } from '@/lib/activity/toolCatalog';

/**
 * Нейтральные названия и описания инструментов для настроек.
 * Порядок массива задаёт порядок строк внутри групп; группы идут в порядке
 * TOOL_GROUP_ORDER. Синхронность с activity-каталогом (TOOL_CATALOG) стережёт
 * __tests__/tool-info.test.ts.
 */
export interface ToolInfo {
  name: string;
  group: ToolGroup;
  title: string;
  description: string;
}

export const TOOL_GROUP_ORDER: { id: ToolGroup; title: string }[] = [
  { id: 'messages', title: 'Сообщения' },
  { id: 'dialogs', title: 'Диалоги и поиск' },
  { id: 'channels', title: 'Каналы и обсуждения' },
  { id: 'media', title: 'Медиа' },
  { id: 'stickers', title: 'Стикеры' },
  { id: 'profile', title: 'Профиль и контакты' },
  { id: 'chatinfo', title: 'Информация о чатах' },
  { id: 'members', title: 'Участники' },
  { id: 'chatsettings', title: 'Настройки чата' },
  { id: 'chatlifecycle', title: 'Создание и удаление' },
  { id: 'utils', title: 'Разное' },
  { id: 'folders', title: 'Папки чатов' },
  { id: 'bots', title: 'Боты и кнопки' },
  { id: 'privacy', title: 'Приватность и аккаунт' },
];

export const TOOL_INFO: ToolInfo[] = [
  // Сообщения
  { name: 'send_text_message', group: 'messages', title: 'Отправка сообщения', description: 'Отправляет текст в чат или комментарий под постом канала.' },
  { name: 'edit_text_message', group: 'messages', title: 'Редактирование сообщения', description: 'Меняет текст сообщения, отправленного ботом.' },
  { name: 'delete_messages', group: 'messages', title: 'Удаление сообщений', description: 'Удаляет сообщения в чате, в том числе у всех.' },
  { name: 'forward_messages', group: 'messages', title: 'Пересылка сообщений', description: 'Пересылает сообщения из одного чата в другой.' },
  { name: 'pin_message', group: 'messages', title: 'Закрепление сообщения', description: 'Закрепляет сообщение в чате.' },
  { name: 'unpin_message', group: 'messages', title: 'Открепление сообщений', description: 'Снимает закрепление с сообщения или со всех закреплённых сообщений чата.' },
  { name: 'send_chat_action', group: 'messages', title: 'Индикатор действия', description: 'Показывает «печатает», «записывает голосовое» и похожие статусы.' },
  { name: 'send_reaction', group: 'messages', title: 'Реакции', description: 'Ставит или снимает реакцию на сообщение.' },
  { name: 'get_message_reactions', group: 'messages', title: 'Просмотр реакций', description: 'Показывает, кто и как отреагировал на сообщение.' },
  { name: 'mark_chat_as_read', group: 'messages', title: 'Отметка прочитанного', description: 'Помечает сообщения в чате прочитанными.' },
  { name: 'get_messages', group: 'messages', title: 'История сообщений', description: 'Читает историю переписки в чате.' },

  // Диалоги и поиск
  { name: 'get_dialogs', group: 'dialogs', title: 'Список диалогов', description: 'Показывает недавние чаты, каналы и переписки.' },
  { name: 'search_messages', group: 'dialogs', title: 'Поиск по сообщениям', description: 'Ищет сообщения по тексту в чате и по всем чатам.' },
  { name: 'delete_dialog', group: 'dialogs', title: 'Удаление диалога', description: 'Удаляет переписку вместе с историей.' },
  { name: 'archive_dialogs', group: 'dialogs', title: 'Архивирование чатов', description: 'Убирает чаты в архив.' },
  { name: 'unarchive_dialogs', group: 'dialogs', title: 'Разархивирование чатов', description: 'Возвращает чаты из архива.' },
  { name: 'get_common_chats', group: 'dialogs', title: 'Общие чаты', description: 'Показывает общие чаты с пользователем.' },

  // Каналы и обсуждения
  { name: 'join_channel', group: 'channels', title: 'Вступление в канал', description: 'Подписывает аккаунт на канал или группу.' },
  { name: 'join_channel_discussion', group: 'channels', title: 'Вход в обсуждение', description: 'Открывает обсуждение канала и присоединяется к нему.' },
  { name: 'get_discussion_messages', group: 'channels', title: 'Чтение обсуждения', description: 'Читает комментарии под постом канала.' },

  // Медиа
  { name: 'send_file', group: 'media', title: 'Отправка файлов', description: 'Отправляет фото, документы, стикеры, голосовые и кружки.' },
  { name: 'view_image', group: 'media', title: 'Просмотр изображений', description: 'Открывает картинку из сообщения и описывает её содержимое.' },
  { name: 'set_profile_photo', group: 'media', title: 'Смена фото профиля', description: 'Обновляет аватар аккаунта.' },
  { name: 'send_voice_note', group: 'media', title: 'Голосовые сообщения', description: 'Записывает и отправляет голосовое сообщение.' },
  { name: 'send_video_note', group: 'media', title: 'Видеокружки', description: 'Записывает и отправляет видеокружок.' },

  // Стикеры
  { name: 'get_sticker_sets', group: 'stickers', title: 'Список стикерпаков', description: 'Показывает установленные наборы стикеров.' },
  { name: 'get_stickers_in_set', group: 'stickers', title: 'Стикеры в наборе', description: 'Показывает стикеры выбранного набора.' },
  { name: 'search_sticker_sets', group: 'stickers', title: 'Поиск стикерпаков', description: 'Ищет наборы стикеров по названию.' },
  { name: 'install_sticker_set', group: 'stickers', title: 'Установка стикерпака', description: 'Добавляет набор стикеров в аккаунт.' },
  { name: 'uninstall_sticker_set', group: 'stickers', title: 'Удаление стикерпака', description: 'Убирает набор стикеров из аккаунта.' },
  { name: 'send_sticker', group: 'stickers', title: 'Отправка стикера', description: 'Отправляет стикер в чат.' },

  // Профиль и контакты
  { name: 'get_profile', group: 'profile', title: 'Просмотр профиля', description: 'Показывает информацию о пользователе или канале.' },
  { name: 'update_profile_info', group: 'profile', title: 'Изменение профиля', description: 'Меняет имя, фамилию и описание аккаунта.' },
  { name: 'update_username', group: 'profile', title: 'Смена username', description: 'Меняет @username аккаунта.' },
  { name: 'add_contact', group: 'profile', title: 'Добавление контакта', description: 'Добавляет пользователя в контакты.' },
  { name: 'delete_contact', group: 'profile', title: 'Удаление контакта', description: 'Убирает пользователя из контактов.' },
  { name: 'get_contacts', group: 'profile', title: 'Список контактов', description: 'Показывает контакты аккаунта.' },

  // Информация о чатах
  { name: 'get_chat_info', group: 'chatinfo', title: 'Информация о чате', description: 'Показывает название, описание и тип чата.' },
  { name: 'check_admin_permissions', group: 'chatinfo', title: 'Проверка прав', description: 'Показывает права аккаунта в чате.' },
  { name: 'get_chat_members', group: 'chatinfo', title: 'Список участников', description: 'Показывает участников чата.' },
  { name: 'get_chat_admin_log', group: 'chatinfo', title: 'Журнал действий', description: 'Показывает историю действий администраторов.' },

  // Участники
  { name: 'invite_to_channel', group: 'members', title: 'Приглашение участника', description: 'Добавляет пользователя в группу или канал.' },
  { name: 'kick_chat_member', group: 'members', title: 'Исключение участника', description: 'Удаляет участника из чата.' },
  { name: 'ban_chat_member', group: 'members', title: 'Бан участника', description: 'Запрещает участнику доступ в чат.' },
  { name: 'restrict_chat_member', group: 'members', title: 'Ограничение участника', description: 'Ограничивает права участника в чате.' },
  { name: 'promote_chat_member', group: 'members', title: 'Назначение администратора', description: 'Выдаёт участнику права администратора.' },
  { name: 'set_chat_admin_rights', group: 'members', title: 'Права администратора', description: 'Настраивает права администратора в чате.' },
  { name: 'set_chat_banned_rights', group: 'members', title: 'Ограничения участника', description: 'Настраивает запреты для участника.' },
  { name: 'set_chat_default_banned_rights', group: 'members', title: 'Права по умолчанию', description: 'Настраивает права новых участников чата.' },

  // Настройки чата
  { name: 'edit_chat_title', group: 'chatsettings', title: 'Название чата', description: 'Меняет название чата.' },
  { name: 'edit_chat_about', group: 'chatsettings', title: 'Описание чата', description: 'Меняет описание чата.' },
  { name: 'edit_chat_photo', group: 'chatsettings', title: 'Фото чата', description: 'Меняет аватар чата.' },
  { name: 'update_chat_public_link', group: 'chatsettings', title: 'Публичная ссылка', description: 'Меняет публичный адрес чата.' },
  { name: 'toggle_chat_signatures', group: 'chatsettings', title: 'Подписи авторов', description: 'Включает или выключает подписи под сообщениями.' },
  { name: 'toggle_join_requests', group: 'chatsettings', title: 'Заявки на вход', description: 'Включает или выключает заявки на вступление.' },
  { name: 'toggle_join_to_send', group: 'chatsettings', title: 'Вход для записи', description: 'Запрещает писать до вступления в чат.' },
  { name: 'toggle_slow_mode', group: 'chatsettings', title: 'Медленный режим', description: 'Настраивает задержку между сообщениями.' },
  { name: 'toggle_forum', group: 'chatsettings', title: 'Режим форума', description: 'Включает или выключает темы в группе.' },
  { name: 'toggle_pre_history_hidden', group: 'chatsettings', title: 'Скрытие истории', description: 'Скрывает старые сообщения от новых участников.' },
  { name: 'toggle_participants_hidden', group: 'chatsettings', title: 'Скрытие участников', description: 'Скрывает список участников чата.' },
  { name: 'edit_chat_location', group: 'chatsettings', title: 'Геолокация чата', description: 'Указывает местоположение чата.' },
  { name: 'toggle_anti_spam', group: 'chatsettings', title: 'Антиспам', description: 'Включает или выключает агрессивный антиспам.' },
  { name: 'set_discussion_group', group: 'chatsettings', title: 'Группа обсуждений', description: 'Привязывает чат обсуждений к каналу.' },

  // Создание и удаление
  { name: 'create_group', group: 'chatlifecycle', title: 'Создание группы', description: 'Создаёт новую группу.' },
  { name: 'create_channel', group: 'chatlifecycle', title: 'Создание канала', description: 'Создаёт новый канал.' },
  { name: 'delete_channel', group: 'chatlifecycle', title: 'Удаление канала', description: 'Удаляет канал или группу.' },

  // Разное
  { name: 'send_poll', group: 'utils', title: 'Опросы', description: 'Отправляет опрос в чат.' },
  { name: 'transcribe_voice_note', group: 'utils', title: 'Расшифровка голосовых', description: 'Переводит голосовое сообщение в текст.' },
  { name: 'read_document_file', group: 'utils', title: 'Чтение документов', description: 'Открывает и читает присланный файл.' },
  { name: 'set_wakeup_timer', group: 'utils', title: 'Напоминание', description: 'Просыпается позже, чтобы вернуться к разговору.' },
  { name: 'mute_chat', group: 'utils', title: 'Отключение уведомлений', description: 'Убирает уведомления от чата.' },
  { name: 'unmute_chat', group: 'utils', title: 'Включение уведомлений', description: 'Возвращает уведомления от чата.' },
  { name: 'send_location', group: 'utils', title: 'Геолокация', description: 'Отправляет точку на карте.' },
  { name: 'send_venue', group: 'utils', title: 'Место на карте', description: 'Отправляет карточку места.' },
  { name: 'search_location', group: 'utils', title: 'Поиск места', description: 'Ищет место по названию.' },

  // Папки чатов
  { name: 'get_chat_folders', group: 'folders', title: 'Папки чатов', description: 'Показывает папки с чатами.' },
  { name: 'create_or_update_chat_folder', group: 'folders', title: 'Настройка папок', description: 'Создаёт или меняет папку чатов.' },
  { name: 'delete_chat_folder', group: 'folders', title: 'Удаление папок', description: 'Удаляет папку чатов.' },

  // Боты и кнопки
  { name: 'get_message_buttons', group: 'bots', title: 'Кнопки сообщения', description: 'Показывает кнопки под сообщением.' },
  { name: 'click_inline_button', group: 'bots', title: 'Нажатие кнопки', description: 'Нажимает кнопку под сообщением.' },
  { name: 'click_reply_keyboard_button', group: 'bots', title: 'Нажатие клавиатуры', description: 'Нажимает кнопку клавиатуры внизу чата.' },
  { name: 'query_inline_bot', group: 'bots', title: 'Запрос к боту', description: 'Спрашивает инлайн-бота.' },
  { name: 'send_inline_bot_result', group: 'bots', title: 'Отправка результата', description: 'Отправляет выбранный результат инлайн-бота.' },
  { name: 'start_bot', group: 'bots', title: 'Запуск бота', description: 'Открывает бота и нажимает «Старт».' },

  // Приватность и аккаунт
  { name: 'get_privacy_settings', group: 'privacy', title: 'Настройки приватности', description: 'Показывает, кто видит профиль и активность.' },
  { name: 'set_privacy_settings', group: 'privacy', title: 'Изменение приватности', description: 'Меняет настройки приватности аккаунта.' },
  { name: 'get_global_settings', group: 'privacy', title: 'Общие настройки', description: 'Показывает общие настройки аккаунта.' },
  { name: 'set_global_settings', group: 'privacy', title: 'Изменение общих настроек', description: 'Меняет общие настройки аккаунта.' },
  { name: 'get_content_settings', group: 'privacy', title: 'Настройки контента', description: 'Показывает фильтр чувствительного контента.' },
  { name: 'set_content_settings', group: 'privacy', title: 'Изменение настроек контента', description: 'Включает или выключает фильтр чувствительного контента.' },
];
