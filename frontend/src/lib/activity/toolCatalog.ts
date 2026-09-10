import {
  Send,
  Pencil,
  Trash2,
  Forward,
  Pin,
  PinOff,
  MousePointerClick,
  Smile,
  BarChart2,
  CheckCheck,
  Inbox,
  Compass,
  Search,
  FolderMinus,
  Archive,
  ArchiveRestore,
  Users,
  Paperclip,
  ImageIcon,
  UserSquare2,
  Mic,
  Video,
  Sticker,
  Library,
  BookPlus,
  BookX,
  UserCircle,
  FilePen,
  AtSign,
  UserPlus,
  UserMinus,
  Contact,
  Info,
  ShieldCheck,
  Users2,
  Megaphone,
  UserX,
  Ban,
  Gavel,
  ShieldPlus,
  UsersRound,
  ScrollText,
  Type,
  FileText,
  Camera,
  Link2,
  Lock,
  Signature,
  Trash,
  DoorOpen,
  DoorClosed,
  Timer,
  MessageSquareDot,
  MessagesSquare,
  Hash,
  MapPin,
  Eye,
  EyeOff,
  Volume2,
  VolumeX,
  MapPinned,
  Landmark,
  MailSearch,
  FolderTree,
  FolderPlus,
  FolderX,
  Keyboard,
  Bot,
  Sparkles,
  PlayCircle,
  ShieldQuestion,
  Settings2,
  Globe2,
  Cookie,
  AlarmClock,
  FileSearch,
  type LucideIcon,
} from 'lucide-react';

export type ToolGroup =
  | 'messages'
  | 'dialogs'
  | 'media'
  | 'profile'
  | 'groups'
  | 'stickers'
  | 'folders'
  | 'bots'
  | 'utils'
  | 'privacy';

export interface ToolMeta {
  ru: string;
  icon: LucideIcon;
  group: ToolGroup;
}

/**
 * Human labels for every Telegram tool the agent can call.
 * Unknown names fall back to a neutral icon and `Инструмент: <имя>`.
 */
export const TOOL_CATALOG: Record<string, ToolMeta> = {
  // Messages and basic communication
  send_text_message: { ru: 'Отправил сообщение', icon: Send, group: 'messages' },
  edit_text_message: { ru: 'Отредактировал сообщение', icon: Pencil, group: 'messages' },
  delete_messages: { ru: 'Удалил сообщения', icon: Trash2, group: 'messages' },
  forward_messages: { ru: 'Переслал сообщения', icon: Forward, group: 'messages' },
  pin_message: { ru: 'Закрепил сообщение', icon: Pin, group: 'messages' },
  unpin_message: { ru: 'Открепил сообщение', icon: PinOff, group: 'messages' },
  unpin_all_messages: { ru: 'Открепил все сообщения', icon: PinOff, group: 'messages' },
  send_chat_action: { ru: 'Отправил действие чата', icon: MousePointerClick, group: 'messages' },
  send_reaction: { ru: 'Поставил реакцию', icon: Smile, group: 'messages' },
  get_message_reactions: { ru: 'Посмотрел реакции', icon: BarChart2, group: 'messages' },
  mark_chat_as_read: { ru: 'Прочитал чат', icon: CheckCheck, group: 'messages' },
  get_messages: { ru: 'Прочитал историю сообщений', icon: Inbox, group: 'messages' },

  // Navigation and dialogs
  get_dialogs: { ru: 'Просмотрел список диалогов', icon: Compass, group: 'dialogs' },
  search_messages: { ru: 'Искал по сообщениям', icon: Search, group: 'dialogs' },
  delete_dialog: { ru: 'Удалил диалог', icon: FolderMinus, group: 'dialogs' },
  archive_dialogs: { ru: 'Архивировал чаты', icon: Archive, group: 'dialogs' },
  unarchive_dialogs: { ru: 'Разархивировал чаты', icon: ArchiveRestore, group: 'dialogs' },
  get_common_chats: { ru: 'Искал общие чаты', icon: Users, group: 'dialogs' },

  // Media
  send_file: { ru: 'Отправил файл', icon: Paperclip, group: 'media' },
  view_image: { ru: 'Посмотрел изображение', icon: ImageIcon, group: 'media' },
  set_profile_photo: { ru: 'Обновил фото профиля', icon: UserSquare2, group: 'media' },
  send_voice_note: { ru: 'Отправил голосовое', icon: Mic, group: 'media' },
  send_video_note: { ru: 'Отправил видеокружок', icon: Video, group: 'media' },

  // Stickers
  get_sticker_sets: { ru: 'Просмотрел стикерпаки', icon: Library, group: 'stickers' },
  get_stickers_in_set: { ru: 'Просмотрел стикеры в паке', icon: Sticker, group: 'stickers' },
  search_sticker_sets: { ru: 'Искал стикерпаки', icon: Search, group: 'stickers' },
  install_sticker_set: { ru: 'Установил стикерпак', icon: BookPlus, group: 'stickers' },
  uninstall_sticker_set: { ru: 'Удалил стикерпак', icon: BookX, group: 'stickers' },
  send_sticker: { ru: 'Отправил стикер', icon: Sticker, group: 'stickers' },

  // Profile and contacts
  get_profile: { ru: 'Посмотрел профиль', icon: UserCircle, group: 'profile' },
  update_profile_info: { ru: 'Обновил информацию профиля', icon: FilePen, group: 'profile' },
  update_username: { ru: 'Сменил username', icon: AtSign, group: 'profile' },
  add_contact: { ru: 'Добавил контакт', icon: UserPlus, group: 'profile' },
  delete_contact: { ru: 'Удалил контакт', icon: UserMinus, group: 'profile' },
  get_contacts: { ru: 'Просмотрел контакты', icon: Contact, group: 'profile' },

  // Groups, channels and permissions
  get_chat_info: { ru: 'Посмотрел информацию о чате', icon: Info, group: 'groups' },
  check_admin_permissions: { ru: 'Проверил права администратора', icon: ShieldCheck, group: 'groups' },
  create_group: { ru: 'Создал группу', icon: Users2, group: 'groups' },
  create_channel: { ru: 'Создал канал', icon: Megaphone, group: 'groups' },
  invite_to_channel: { ru: 'Добавил участника', icon: UserPlus, group: 'groups' },
  kick_chat_member: { ru: 'Исключил участника', icon: UserX, group: 'groups' },
  ban_chat_member: { ru: 'Забанил участника', icon: Ban, group: 'groups' },
  restrict_chat_member: { ru: 'Ограничил участника', icon: Gavel, group: 'groups' },
  promote_chat_member: { ru: 'Назначил администратором', icon: ShieldPlus, group: 'groups' },
  get_chat_members: { ru: 'Просмотрел участников', icon: UsersRound, group: 'groups' },
  get_chat_admin_log: { ru: 'Просмотрел журнал админ-действий', icon: ScrollText, group: 'groups' },
  edit_chat_title: { ru: 'Изменил название чата', icon: Type, group: 'groups' },
  edit_chat_about: { ru: 'Изменил описание чата', icon: FileText, group: 'groups' },
  edit_chat_photo: { ru: 'Изменил фото чата', icon: Camera, group: 'groups' },
  update_chat_public_link: { ru: 'Обновил публичную ссылку', icon: Link2, group: 'groups' },
  set_chat_default_banned_rights: { ru: 'Настроил права по умолчанию', icon: Lock, group: 'groups' },
  toggle_chat_signatures: { ru: 'Переключил подписи', icon: Signature, group: 'groups' },
  delete_channel: { ru: 'Удалил канал', icon: Trash, group: 'groups' },
  toggle_join_requests: { ru: 'Переключил заявки на вход', icon: DoorOpen, group: 'groups' },
  toggle_join_to_send: { ru: 'Переключил вступление для записи', icon: DoorClosed, group: 'groups' },
  toggle_slow_mode: { ru: 'Переключил медленный режим', icon: Timer, group: 'groups' },
  set_discussion_group: { ru: 'Привязал группу обсуждений', icon: MessageSquareDot, group: 'groups' },
  join_channel_discussion: { ru: 'Открыл обсуждение канала', icon: MessagesSquare, group: 'groups' },
  get_discussion_messages: { ru: 'Прочитал обсуждение', icon: Hash, group: 'groups' },
  toggle_forum: { ru: 'Переключил режим форума', icon: FolderTree, group: 'groups' },
  toggle_pre_history_hidden: { ru: 'Скрыл историю для новых', icon: EyeOff, group: 'groups' },
  toggle_participants_hidden: { ru: 'Скрыл список участников', icon: Eye, group: 'groups' },
  edit_chat_location: { ru: 'Изменил геолокацию чата', icon: MapPin, group: 'groups' },
  toggle_anti_spam: { ru: 'Переключил антиспам', icon: ShieldQuestion, group: 'groups' },
  set_chat_admin_rights: { ru: 'Настроил права администратора', icon: Settings2, group: 'groups' },
  set_chat_banned_rights: { ru: 'Настроил ограничения', icon: Ban, group: 'groups' },

  // Misc utilities
  join_channel: { ru: 'Присоединился к каналу', icon: PlayCircle, group: 'utils' },
  send_poll: { ru: 'Отправил опрос', icon: BarChart2, group: 'utils' },
  transcribe_voice_note: { ru: 'Расшифровал голосовое', icon: Volume2, group: 'utils' },
  read_document_file: { ru: 'Прочитал документ', icon: FileSearch, group: 'utils' },
  set_wakeup_timer: { ru: 'Поставил таймер-напоминание', icon: AlarmClock, group: 'utils' },
  mute_chat: { ru: 'Выключил уведомления чата', icon: VolumeX, group: 'utils' },
  unmute_chat: { ru: 'Включил уведомления чата', icon: Volume2, group: 'utils' },
  send_location: { ru: 'Отправил геолокацию', icon: MapPinned, group: 'utils' },
  send_venue: { ru: 'Отправил карточку места', icon: Landmark, group: 'utils' },
  search_location: { ru: 'Искал место на карте', icon: MailSearch, group: 'utils' },

  // Chat folders
  get_chat_folders: { ru: 'Просмотрел папки чатов', icon: FolderTree, group: 'folders' },
  create_or_update_chat_folder: { ru: 'Обновил папку чатов', icon: FolderPlus, group: 'folders' },
  delete_chat_folder: { ru: 'Удалил папку чатов', icon: FolderX, group: 'folders' },

  // Bot interaction
  get_message_buttons: { ru: 'Посмотрел кнопки сообщения', icon: Keyboard, group: 'bots' },
  click_inline_button: { ru: 'Нажал кнопку в сообщении', icon: MousePointerClick, group: 'bots' },
  click_reply_keyboard_button: { ru: 'Нажал кнопку клавиатуры', icon: Keyboard, group: 'bots' },
  query_inline_bot: { ru: 'Запросил инлайн-бота', icon: Bot, group: 'bots' },
  send_inline_bot_result: { ru: 'Отправил результат инлайн-бота', icon: Sparkles, group: 'bots' },
  start_bot: { ru: 'Запустил бота', icon: PlayCircle, group: 'bots' },

  // Privacy and account settings
  get_privacy_settings: { ru: 'Просмотрел настройки приватности', icon: ShieldQuestion, group: 'privacy' },
  set_privacy_settings: { ru: 'Изменил настройки приватности', icon: Lock, group: 'privacy' },
  get_global_settings: { ru: 'Просмотрел общие настройки', icon: Globe2, group: 'privacy' },
  set_global_settings: { ru: 'Изменил общие настройки', icon: Settings2, group: 'privacy' },
  get_content_settings: { ru: 'Просмотрел настройки контента', icon: Cookie, group: 'privacy' },
  set_content_settings: { ru: 'Изменил настройки контента', icon: Cookie, group: 'privacy' },
};

const FALLBACK_ICON = Bot;

export function getToolMeta(name: string): ToolMeta {
  return (
    TOOL_CATALOG[name] ?? {
      ru: `Инструмент: ${name}`,
      icon: FALLBACK_ICON,
      group: 'utils',
    }
  );
}
