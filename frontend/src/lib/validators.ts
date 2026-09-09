import { z } from 'zod';

// ── Security: agent_id from URL must be alphanumeric + dash/underscore only ───
// Prevents path traversal attacks
export const agentIdSchema = z
  .string()
  .min(1, 'ID агента обязателен')
  .max(64, 'ID агента слишком длинный')
  .regex(
    /^[a-zA-Z0-9_-]+$/,
    'Недопустимые символы в ID агента'
  );

// ── Phone number in E.164 format ──────────────────────────────────────────────
export const phoneNumberSchema = z
  .string()
  .min(1, 'Номер телефона обязателен')
  .transform((val) => {
    // Удаляем все пробелы, дефисы и скобки
    const cleaned = val.replace(/[\s\-\(\)]/g, '');
    // Если строка не пустая и не начинается с '+', добавляем '+'
    if (cleaned && !cleaned.startsWith('+')) {
      return '+' + cleaned;
    }
    return cleaned;
  })
  .refine(
    (val) => /^\+[1-9]\d{6,18}$/.test(val),
    'Номер телефона должен быть в формате E.164 (например: +79991234567)'
  );

// ── Email ─────────────────────────────────────────────────────────────────────
export const emailSchema = z
  .string()
  .min(1, 'Email обязателен')
  .email('Введите корректный email')
  .max(254, 'Email слишком длинный');

// ── Password ─────────────────────────────────────────────────────────────────
export const passwordSchema = z
  .string()
  .min(8, 'Пароль должен быть не менее 8 символов')
  .max(128, 'Пароль слишком длинный');

// ── Auth forms ────────────────────────────────────────────────────────────────
export const loginSchema = z.object({
  email: emailSchema,
  password: z.string().min(1, 'Пароль обязателен'),
});

export const registerSchema = z.object({
  email: emailSchema,
  password: passwordSchema,
  confirmPassword: z.string(),
}).refine(
  (data) => data.password === data.confirmPassword,
  {
    message: 'Пароли не совпадают',
    path: ['confirmPassword'],
  }
);

// ── Onboarding schemas ────────────────────────────────────────────────────────

// Step 1: Agent name
export const agentNameSchema = z.object({
  name: z
    .string()
    .min(1, 'Имя агента обязательно')
    .max(64, 'Имя агента не должно превышать 64 символа')
    .trim(),
});

// Step 2: Soul / character prompt
export const soulPromptSchema = z.object({
  soul_prompt: z
    .string()
    .min(10, 'Характер должен содержать хотя бы 10 символов')
    .max(50_000, 'Характер не должен превышать 50 000 символов')
    .trim(),
});

// Step 4a: Telegram credentials
// API ID и Hash берутся из приложения сервера, пользователь вводит только телефон.
export const telegramCredentialsSchema = z.object({
  phone_number: phoneNumberSchema,
});

// Step 4b: Telegram code
export const telegramCodeSchema = z.object({
  code: z
    .string()
    .min(5, 'Код должен содержать минимум 5 цифр')
    .max(8, 'Код не должен превышать 8 символов')
    .regex(/^\d+$/, 'Код должен содержать только цифры'),
});

// Step 4c: 2FA password
export const telegram2FASchema = z.object({
  password: z
    .string()
    .min(1, '2FA пароль обязателен')
    .max(128, '2FA пароль слишком длинный'),
});

// ── Agent settings form ───────────────────────────────────────────────────────
export const agentSettingsSchema = z.object({
  name: z
    .string()
    .min(1, 'Имя агента обязательно')
    .max(64, 'Имя агента не должно превышать 64 символа')
    .trim(),
  soul_prompt: z
    .string()
    .min(0)
    .max(50_000, 'Характер не должен превышать 50 000 символов')
    .trim(),
  reasoning_effort: z.enum(['none', 'medium', 'high']).optional(),
});

// ── Trigger message form ──────────────────────────────────────────────────────
export const triggerMessageSchema = z.object({
  peer: z
    .string()
    .min(1, 'Получатель обязателен')
    .max(128, 'Получатель слишком длинный')
    .trim(),
  text: z
    .string()
    .min(1, 'Текст сообщения обязателен')
    .max(4096, 'Сообщение не должно превышать 4096 символов')
    .trim(),
});

// ── Type inference helpers ────────────────────────────────────────────────────
export type LoginFormValues = z.infer<typeof loginSchema>;
export type RegisterFormValues = z.infer<typeof registerSchema>;
export type AgentNameValues = z.infer<typeof agentNameSchema>;
export type SoulPromptValues = z.infer<typeof soulPromptSchema>;
export type TelegramCredentialsValues = z.infer<typeof telegramCredentialsSchema>;
export type TelegramCodeValues = z.infer<typeof telegramCodeSchema>;
export type Telegram2FAValues = z.infer<typeof telegram2FASchema>;
export type AgentSettingsValues = z.infer<typeof agentSettingsSchema>;
export type TriggerMessageValues = z.infer<typeof triggerMessageSchema>;
