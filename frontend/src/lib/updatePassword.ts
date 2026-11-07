interface PasswordAccountScope {
  userId: string;
  signal: AbortSignal;
}

interface PasswordSessionReader {
  getSession(): Promise<{
    data: { session: { access_token: string; user: { id: string } } | null };
    error: { message: string } | null;
  }>;
}

export async function updateAccountPassword(
  password: string,
  scope: PasswordAccountScope,
  auth: PasswordSessionReader,
): Promise<void> {
  scope.signal.throwIfAborted();
  const { data: { session }, error } = await auth.getSession();
  scope.signal.throwIfAborted();
  if (error) throw new Error(error.message);
  if (!session || session.user.id !== scope.userId) {
    throw new DOMException('Account changed', 'AbortError');
  }

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const apiKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !apiKey) throw new Error('Не удалось настроить смену пароля.');

  // updateUser saves its response into shared auth state, even if its owner has left.
  const response = await fetch(`${url.replace(/\/$/, '')}/auth/v1/user`, {
    method: 'PUT',
    headers: {
      apikey: apiKey,
      Authorization: `Bearer ${session.access_token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ password }),
    signal: scope.signal,
    credentials: 'omit',
    redirect: 'error',
  });
  scope.signal.throwIfAborted();
  if (response.ok) return;

  let message = 'Не удалось обновить пароль. Попробуйте снова.';
  if (response.headers.get('content-type')?.includes('application/json')) {
    const body: unknown = await response.json();
    scope.signal.throwIfAborted();
    if (body && typeof body === 'object') {
      const details = [
        'msg' in body ? body.msg : null,
        'message' in body ? body.message : null,
        'error_description' in body ? body.error_description : null,
      ];
      const detail = details.find((value) => typeof value === 'string' && value.length > 0);
      if (typeof detail === 'string') message = detail;
    }
  }
  throw new Error(message);
}
