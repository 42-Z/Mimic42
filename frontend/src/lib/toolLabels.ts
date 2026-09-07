// Human-readable Russian labels for all 89 Telegram tools.
// Each function receives the tool arguments and returns a descriptive string.

export type ToolLabelFn = (args: Record<string, unknown>) => string;

/** Narrows an unknown tool payload to an args record ({} when absent). */
export function toolArgs(payload: unknown): Record<string, unknown> {
  if (typeof payload === 'object' && payload !== null && !Array.isArray(payload)) {
    return payload as Record<string, unknown>;
  }
  return {};
}

const _peer = (a: Record<string, unknown>): string => {
  const p =
    a.peer ??
    a.entity ??
    a.channel ??
    a.user ??
    a.to_peer ??
    a.from_peer ??
    '';
  return String(p);
};

export const TOOL_LABELS: Record<string, ToolLabelFn> = {
  // Category 1: Messages and Basic Communication
  send_text_message: (a) => `Отправил сообщение ${_peer(a)}`,
  edit_text_message: (a) => `Отредактировал сообщение в ${_peer(a)}`,
  delete_messages: (a) => `Удалил сообщения в ${_peer(a)}`,
  forward_messages: (a) =>
    `Переслал сообщения из ${a.from_peer ?? ''} в ${a.to_peer ?? ''}`,
  pin_message: (a) => `Закрепил сообщение в ${_peer(a)}`,
  unpin_message: (a) => `Открепил сообщение в ${_peer(a)}`,
  unpin_all_messages: (a) => `Открепил все сообщения в ${_peer(a)}`,
  send_chat_action: (a) => `Показал действие «${a.action}» в ${_peer(a)}`,
  send_reaction: (a) =>
    `Поставил реакцию ${a.emoji ?? a.reaction ?? ''} в ${_peer(a)}`,
  get_message_reactions: (a) => `Посмотрел реакции на сообщение в ${_peer(a)}`,
  mark_chat_as_read: (a) => `Отметил чат ${_peer(a)} как прочитанный`,

  // Category 2: Dialogs and Search
  get_messages: (a) => `Загрузил историю сообщений ${_peer(a)}`,
  get_dialogs: () => `Посмотрел список чатов`,
  search_messages: (a) => `Искал «${a.query ?? ''}» в ${_peer(a)}`,
  delete_dialog: (a) => `Удалил диалог ${_peer(a)}`,
  archive_dialogs: () => `Архивировал чаты`,
  unarchive_dialogs: () => `Разархивировал чаты`,
  get_common_chats: (a) => `Посмотрел общие чаты с ${_peer(a)}`,

  // Category 3: Media and Files
  send_file: (a) => `Отправил файл в ${_peer(a)}`,
  view_image: () => `Посмотрел изображение`,
  set_profile_photo: () => `Сменил фото профиля`,
  send_voice_note: (a) => `Отправил голосовое в ${_peer(a)}`,
  send_video_note: (a) => `Отправил видеосообщение в ${_peer(a)}`,
  transcribe_voice_note: () => `Расшифровал голосовое`,
  read_document_file: () => `Прочитал документ`,

  // Category 4: Stickers
  get_sticker_sets: () => `Посмотрел стикер-паки`,
  get_stickers_in_set: (a) => `Посмотрел стикеры из набора «${a.set_short_name ?? ''}»`,
  search_sticker_sets: (a) => `Искал стикеры по запросу «${a.query ?? ''}»`,
  install_sticker_set: (a) => `Установил стикер-пак «${a.set_short_name ?? ''}»`,
  uninstall_sticker_set: (a) => `Удалил стикер-пак «${a.set_short_name ?? ''}»`,
  send_sticker: (a) => `Отправил стикер в ${_peer(a)}`,

  // Category 5: Profile and Contacts
  get_profile: (a) => `Посмотрел профиль ${_peer(a)}`,
  update_profile_info: () => `Обновил информацию профиля`,
  update_username: (a) => `Сменил username на @${a.username ?? ''}`,
  add_contact: (a) => `Добавил контакт ${a.first_name ?? ''} ${a.last_name ?? ''}`,
  delete_contact: (a) => `Удалил контакт ${_peer(a)}`,
  get_contacts: () => `Посмотрел список контактов`,

  // Category 6: Groups and Channels
  get_chat_info: (a) => `Посмотрел информацию о чате ${_peer(a)}`,
  check_admin_permissions: (a) => `Проверил права админа в ${_peer(a)}`,
  create_group: (a) => `Создал группу «${a.title ?? ''}»`,
  create_channel: (a) => `Создал канал «${a.title ?? ''}»`,
  invite_to_channel: (a) => `Пригласил в канал ${_peer(a)}`,
  kick_chat_member: (a) => `Исключил ${a.user ?? ''} из ${_peer(a)}`,
  ban_chat_member: (a) => `Забанил ${a.user ?? ''} в ${_peer(a)}`,
  restrict_chat_member: (a) => `Ограничил права ${a.user ?? ''} в ${_peer(a)}`,
  promote_chat_member: (a) => `Повысил ${a.user ?? ''} до админа в ${_peer(a)}`,
  get_chat_members: (a) => `Посмотрел участников ${_peer(a)}`,
  get_chat_admin_log: (a) => `Посмотрел лог админов ${_peer(a)}`,
  edit_chat_title: (a) => `Сменил название ${_peer(a)} на «${a.title ?? ''}»`,
  edit_chat_about: (a) => `Обновил описание ${_peer(a)}`,
  edit_chat_photo: (a) => `Сменил фото ${_peer(a)}`,
  update_chat_public_link: (a) => `Обновил публичную ссылку ${_peer(a)}`,
  set_chat_default_banned_rights: (a) => `Установил права по умолчанию в ${_peer(a)}`,
  toggle_chat_signatures: (a) => `Переключил подписи в ${_peer(a)}`,
  delete_channel: (a) => `Удалил канал ${_peer(a)}`,
  toggle_join_requests: (a) => `Переключил заявки на вступление в ${_peer(a)}`,
  toggle_join_to_send: (a) => `Переключил «вступить, чтобы писать» в ${_peer(a)}`,
  toggle_slow_mode: (a) => `Переключил медленный режим в ${_peer(a)}`,
  set_discussion_group: (a) => `Установил группу обсуждения для ${_peer(a)}`,
  toggle_forum: (a) => `Переключил форум в ${_peer(a)}`,
  toggle_pre_history_hidden: (a) => `Переключил скрытие истории в ${_peer(a)}`,
  toggle_participants_hidden: (a) => `Переключил видимость участников в ${_peer(a)}`,
  edit_chat_location: (a) => `Установил геолокацию для ${_peer(a)}`,
  toggle_anti_spam: (a) => `Переключил антиспам в ${_peer(a)}`,
  set_chat_admin_rights: (a) => `Установил права админа в ${_peer(a)}`,
  set_chat_banned_rights: (a) => `Установил бан-прав в ${_peer(a)}`,
  join_channel: (a) => `Вступил в канал ${_peer(a)}`,

  // Category 7: Polls and Timers
  send_poll: (a) => `Отправил опрос в ${_peer(a)}: «${a.question ?? ''}»`,
  set_wakeup_timer: (a) => `Установил таймер на ${a.delay_seconds ?? 0} сек`,

  // Category 8: Chat Folders
  get_chat_folders: () => `Посмотрел папки чатов`,
  create_or_update_chat_folder: (a) => `Создал/обновил папку «${a.title ?? ''}»`,
  delete_chat_folder: () => `Удалил папку чатов`,

  // Category 9: Inline Bots and Buttons
  get_message_buttons: (a) => `Посмотрел кнопки сообщения в ${_peer(a)}`,
  click_inline_button: (a) => `Нажал inline-кнопку в ${_peer(a)}`,
  click_reply_keyboard_button: (a) => `Нажал reply-кнопку в ${_peer(a)}`,
  query_inline_bot: (a) => `Сделал inline-запрос боту ${a.bot_username ?? ''}`,
  send_inline_bot_result: (a) => `Отправил inline-результат в ${_peer(a)}`,
  start_bot: (a) => `Запустил бота @${a.bot_username ?? ''}`,

  // Category 10: Privacy and Settings
  get_privacy_settings: (a) => `Посмотрел настройки приватности «${a.key ?? ''}»`,
  set_privacy_settings: (a) => `Изменил приватность «${a.key ?? ''}»`,
  get_global_settings: () => `Посмотрел глобальные настройки`,
  set_global_settings: () => `Изменил глобальные настройки`,
  get_content_settings: () => `Посмотрел настройки контента`,
  set_content_settings: () => `Изменил настройки контента`,

  // Category 11: Location
  send_location: (a) => `Отправил геолокацию в ${_peer(a)}`,
  send_venue: (a) => `Отправил место в ${_peer(a)}`,
  search_location: (a) => `Искал место «${a.query ?? ''}»`,

  // Category 12: Mute/Unmute
  mute_chat: (a) => `Заглушил чат ${_peer(a)}`,
  unmute_chat: (a) => `Включил уведомления в ${_peer(a)}`,
};

export const FALLBACK_TOOL_LABEL: ToolLabelFn = (a) => {
  const name = a.__tool_name ?? 'tool';
  return `Выполнил действие «${name}»`;
};

export function getToolLabel(name: string, args: Record<string, unknown>): string {
  // eslint-disable-next-line security/detect-object-injection -- dispatch table guarded by `if (fn)` below
  const fn = TOOL_LABELS[name];
  if (fn) {
    try {
      return fn(args);
    } catch {
      return `Выполнил действие «${name}»`;
    }
  }
  return `Выполнил действие «${name}»`;
}
