/**
 * Machine identity of Telegram failures → human Russian phrases.
 * The `error_code` is the exception class name captured by the backend.
 */
const ERROR_CATALOG: Record<string, string> = {
  FloodWaitError: 'Telegram просит подождать',
  FloodPremiumWaitError: 'Telegram просит подождать',
  SlowModeWaitError: 'В чате включён медленный режим',
  ChatAdminRequiredError: 'Нет прав администратора в чате',
  ChatWriteForbiddenError: 'Нельзя писать в этот чат',
  ChatSendMediaForbiddenError: 'Нельзя отправлять медиа в этот чат',
  ChatSendStickersForbiddenError: 'Нельзя отправлять стикеры в этот чат',
  ChatSendPollForbiddenError: 'Нельзя отправлять опросы в этот чат',
  ChatSendInlineForbiddenError: 'Нельзя отправлять инлайн-сообщения в этот чат',
  ChatSendGameForbiddenError: 'Нельзя отправлять игры в этот чат',
  ChatForwardsRestrictedError: 'В чате запрещены пересылки',
  PeerIdInvalidError: 'Не удалось определить собеседника',
  UserIsBlockedError: 'Пользователь заблокировал агента',
  UserDeactivatedBanError: 'Аккаунт пользователя заблокирован',
  UserNotMutualContactError: 'Нет взаимного контакта с пользователем',
  UserPrivacyRestrictedError: 'Настройки приватности не позволяют это сделать',
  UserChannelsTooMuchError: 'У пользователя слишком много каналов',
  UserNotParticipantError: 'Пользователь не участник этого чата',
  UserAdminInvalidError: 'Нельзя применить действие к администратору',
  UserBannedInChannelError: 'Пользователь заблокирован в этом чате',
  InputUserDeactivatedError: 'Аккаунт пользователя деактивирован',
  ChannelPrivateError: 'Канал приватный и недоступен',
  ChannelInvalidError: 'Не удалось определить канал',
  ChatAdminInviteRequiredError: 'Требуются права администратора',
  RightForbiddenError: 'Недостаточно прав для этого действия',
  MessageIdInvalidError: 'Сообщение не найдено или устарело',
  MessageDeleteForbiddenError: 'Нельзя удалить это сообщение',
  MessageTooLongError: 'Сообщение слишком длинное',
  MessageEmptyError: 'Сообщение пустое',
  MediaEmptyError: 'Медиафайл недоступен',
  FileReferenceExpiredError: 'Ссылка на файл устарела',
  FilePartMissingError: 'Ошибка передачи файла',
  PhotoInvalidError: 'Некорректное изображение',
  StickerSetInvalidError: 'Стикерпак не найден',
  WebpageCurlFailedError: 'Не удалось загрузить файл по ссылке',
  WebpageMediaEmptyError: 'По ссылке нет подходящего медиа',
  UsernameNotOccupiedError: 'Такое имя не занято',
  UsernameInvalidError: 'Некорректное имя пользователя',
  AboutTooLongError: 'Описание слишком длинное',
  AuthKeyDuplicatedError: 'Сессия используется в другом месте',
  AuthKeyUnregisteredError: 'Сессия отозвана, требуется переподключение',
  SessionRevokedError: 'Сессия отозвана, требуется переподключение',
  SessionPasswordNeededError: 'Требуется пароль двухфакторной аутентификации',
  PhoneNumberInvalidError: 'Некорректный номер телефона',
  ApiIdInvalidError: 'Неверные API-данные',
  TimeoutError: 'Telegram не ответил вовремя',
  ConnectionError: 'Ошибка соединения с Telegram',
  ValueError: 'Некорректные параметры запроса',
  TypeError: 'Некорректные параметры запроса',
};

export function describeError(errorCode: unknown, rawError?: string | null): string {
  if (typeof errorCode === 'string' && ERROR_CATALOG[errorCode]) {
    return ERROR_CATALOG[errorCode];
  }
  return rawError?.trim() ? rawError : 'Ошибка Telegram';
}
