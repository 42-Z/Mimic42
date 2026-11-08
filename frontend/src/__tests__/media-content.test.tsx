import { afterEach, beforeEach, describe, expect, mock, spyOn, test } from 'bun:test';
import { focusManager, onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import type { ReactElement } from 'react';
import { MediaContent } from '@/components/activity/MediaContent';
import { apiClient } from '@/lib/api';
import { queryKeys } from '@/lib/queryClient';
import type { MediaItem } from '@/types';

let queryClient: QueryClient;

beforeEach(() => {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
});

afterEach(() => {
  queryClient.clear();
  focusManager.setFocused(undefined);
  onlineManager.setOnline(true);
});

function renderMedia(ui: ReactElement) {
  return render(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    ),
  });
}

function mockMediaApi() {
  return spyOn(apiClient, 'get').mockImplementation(
    async (url: string) =>
      ({
        data: url.includes('/media-link/')
          ? { url: `https://storage.test/${url.split('/media-link/')[1]}`, expires_in: 43200 }
          : new Blob(['test-media']),
      }) as never,
  );
}

function item(kind: MediaItem['kind'], name: string): MediaItem {
  return {
    kind,
    name,
    mime_type: 'image/jpeg',
    size: 1024,
    storage_path: null,
  };
}

function mediaError(media: HTMLElement, code: number | null) {
  Object.defineProperty(media, 'error', {
    configurable: true,
    value: code === null ? null : { code },
  });
  fireEvent.error(media);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe('MediaContent', () => {
  test('несколько картинок идут в ряд в отдельной галерее', () => {
    renderMedia(
      <MediaContent
        agentId="a1"
        items={[item('photo', '1.jpeg'), item('photo', '2.jpeg'), item('photo', '3.jpeg')]}
      />,
    );
    const gallery = screen.getByTestId('media-gallery');
    expect(within(gallery).getAllByRole('button')).toHaveLength(3);
  });

  test('одна картинка рендерится как раньше, без галереи', () => {
    renderMedia(<MediaContent agentId="a1" items={[item('photo', 'solo.jpeg')]} />);
    expect(screen.queryByTestId('media-gallery')).toBeNull();
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  test('не-картинки не попадают в галерею', () => {
    renderMedia(
      <MediaContent
        agentId="a1"
        items={[item('photo', '1.jpeg'), item('photo', '2.jpeg'), item('doc', 'report.pdf')]}
      />,
    );
    const gallery = screen.getByTestId('media-gallery');
    expect(within(gallery).getAllByRole('button')).toHaveLength(2);
    expect(screen.getByText(/report\.pdf/)).toBeTruthy();
  });

  test('стрелки клавиатуры листают галерею в ту же сторону, что и кнопки', () => {
    renderMedia(
      <MediaContent
        agentId="a1"
        items={[item('photo', '1.jpeg'), item('photo', '2.jpeg'), item('photo', '3.jpeg')]}
      />,
    );
    const gallery = screen.getByTestId('media-gallery');
    fireEvent.click(within(gallery).getAllByRole('button')[0]!);
    expect(screen.getByRole('heading', { name: '1.jpeg' })).toBeTruthy();

    fireEvent.keyDown(document, { key: 'ArrowRight' });
    expect(screen.getByRole('heading', { name: '2.jpeg' })).toBeTruthy();

    fireEvent.keyDown(document, { key: 'ArrowLeft' });
    expect(screen.getByRole('heading', { name: '1.jpeg' })).toBeTruthy();

    // Кнопка «назад» — в ту же сторону, что ArrowLeft: заворачивается на 3.jpeg.
    fireEvent.click(screen.getByLabelText('Предыдущее изображение'));
    expect(screen.getByRole('heading', { name: '3.jpeg' })).toBeTruthy();
  });
});

describe('MediaContent: стикеры', () => {
  function storedSticker(mimeType: string, name: string): MediaItem {
    return {
      kind: 'sticker',
      name,
      mime_type: mimeType,
      size: 1024,
      storage_path: `a1/archive/${name}`,
    };
  }

  const createDescriptor = Object.getOwnPropertyDescriptor(URL, 'createObjectURL');
  const revokeDescriptor = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL');

  beforeEach(() => {
    let sequence = 0;
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: mock(() => `blob:media-${++sequence}`),
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: mock((_url: string) => {}),
    });
    mockMediaApi();
  });

  afterEach(() => {
    cleanup();
    mock.restore();
    if (createDescriptor) {
      Object.defineProperty(URL, 'createObjectURL', createDescriptor);
    } else {
      Reflect.deleteProperty(URL, 'createObjectURL');
    }
    if (revokeDescriptor) {
      Object.defineProperty(URL, 'revokeObjectURL', revokeDescriptor);
    } else {
      Reflect.deleteProperty(URL, 'revokeObjectURL');
    }
  });

  test('WebP остаётся изображением и открывается в лайтбоксе', async () => {
    const sticker = storedSticker('image/webp', 'static.webp');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    expect(await screen.findByRole('img', { name: sticker.name })).toBeTruthy();
    expect(apiClient.get).toHaveBeenCalledWith(
      '/agents/a1/media/a1/archive/static.webp',
      { responseType: 'blob' },
    );
    fireEvent.click(screen.getByRole('button', { name: sticker.name }));
    const dialog = screen.getByRole('dialog');
    expect(await within(dialog).findByRole('img', { name: sticker.name })).toBeTruthy();
  });

  test('WebM отображается видео с контролами, не картинкой', async () => {
    const sticker = storedSticker('video/webm', 'video.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    const video = await screen.findByLabelText(`Стикер ${sticker.name}`);
    expect(video.tagName).toBe('VIDEO');
    expect(video.hasAttribute('controls')).toBe(true);
    expect(video.hasAttribute('loop')).toBe(true);
    expect(video.hasAttribute('playsinline')).toBe(true);
    expect((video as HTMLVideoElement).muted).toBe(true);
    expect(video.hasAttribute('autoplay')).toBe(false);
    expect(video.getAttribute('src')).toBe('https://storage.test/a1/archive/video.webm');
    expect(apiClient.get).toHaveBeenCalledWith('/agents/a1/media-link/a1/archive/video.webm', { accountScope: undefined });
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.queryByTestId('media-gallery')).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('TGS сразу показывает плашку без скачивания', () => {
    const sticker = storedSticker('application/x-tgsticker', 'animation.tgs');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    expect(screen.getByText('animation.tgs (анимированный стикер)')).toBeTruthy();
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  test('неизвестный MIME стикера не создаёт сломанный img', () => {
    const sticker = storedSticker('application/octet-stream', 'legacy.sticker');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    expect(screen.getByText('legacy.sticker (предпросмотр недоступен)')).toBeTruthy();
    expect(screen.queryByRole('img')).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  test('пустой MIME стикера безопасно заменяется плашкой', () => {
    renderMedia(<MediaContent agentId="a1" items={[storedSticker('', 'legacy.sticker')]} />);
    expect(screen.getByText('legacy.sticker (предпросмотр недоступен)')).toBeTruthy();
    expect(screen.queryByRole('img')).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  test('WebM и TGS не участвуют в галерее и её навигации', async () => {
    const photo: MediaItem = {
      ...item('photo', 'photo.jpeg'),
      storage_path: 'a1/archive/photo.jpeg',
    };
    const webp = storedSticker('image/webp', 'static.webp');
    renderMedia(
      <MediaContent
        agentId="a1"
        items={[
          photo,
          storedSticker('video/webm', 'video.webm'),
          storedSticker('application/x-tgsticker', 'animation.tgs'),
          webp,
        ]}
      />,
    );
    const gallery = screen.getByTestId('media-gallery');
    await within(gallery).findByRole('img', { name: webp.name });
    expect(within(gallery).getAllByRole('button')).toHaveLength(2);
    fireEvent.click(within(gallery).getByRole('button', { name: photo.name }));
    // Флеш микротасков внутри act: при открытии лайтбокса и смене изображения
    // резолвится загрузка, и без этого обновление выпадает за пределы act.
    await act(async () => {});
    fireEvent.keyDown(document, { key: 'ArrowRight' });
    expect(screen.getByRole('heading', { name: webp.name })).toBeTruthy();
    await act(async () => {});
    fireEvent.keyDown(document, { key: 'ArrowRight' });
    expect(screen.getByRole('heading', { name: photo.name })).toBeTruthy();
    await act(async () => {});
  });

  test('ошибка декодирования старого WebP заменяет img плашкой', async () => {
    const sticker = storedSticker('image/webp', 'legacy.webp');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    fireEvent.error(await screen.findByRole('img', { name: sticker.name }));
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.getByText('legacy.webp (недоступно)')).toBeTruthy();
  });

  test('ошибка декодирования WebM заменяет video плашкой', async () => {
    const sticker = storedSticker('video/webm', 'broken.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    const video = await screen.findByLabelText(`Стикер ${sticker.name}`);
    Object.defineProperty(video, 'error', { value: { code: 3 } });
    fireEvent.error(video);
    expect(screen.queryByLabelText(`Стикер ${sticker.name}`)).toBeNull();
    expect(screen.getByText('broken.webm (недоступно)')).toBeTruthy();
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  test('смонтированное медиа обновляет подпись до истечения срока', async () => {
    let signatures = 0;
    spyOn(apiClient, 'get').mockImplementation(async () => ({
      data: { url: `https://storage.test/clip-${++signatures}.webm`, expires_in: 0.2 },
    }) as never);
    const sticker = storedSticker('video/webm', 'long-open.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    await waitFor(() => expect(screen.getByLabelText(`Стикер ${sticker.name}`).getAttribute('src'))
      .toBe('https://storage.test/clip-1.webm'));
    await waitFor(() => expect(screen.getByLabelText(`Стикер ${sticker.name}`).getAttribute('src'))
      .toBe('https://storage.test/clip-2.webm'));
  });

  test('после ошибки доступа медиа получает новую ссылку, повторный отказ ограничен', async () => {
    let signatures = 0;
    spyOn(apiClient, 'get').mockImplementation(async () => ({
      data: { url: `https://storage.test/clip-${++signatures}.webm`, expires_in: 43200 },
    }) as never);
    const sticker = storedSticker('video/webm', 'expired.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    const video = await screen.findByLabelText(`Стикер ${sticker.name}`);
    Object.defineProperty(video, 'error', { configurable: true, value: { code: 4 } });
    fireEvent.error(video);
    await waitFor(() => expect(screen.getByLabelText(`Стикер ${sticker.name}`).getAttribute('src'))
      .toBe('https://storage.test/clip-2.webm'));
    fireEvent.error(screen.getByLabelText(`Стикер ${sticker.name}`));
    expect(await screen.findByText('expired.webm (недоступно)')).toBeTruthy();
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  test('повторная подпись с тем же URL явно перезагружает плеер и возвращает позицию', async () => {
    const sticker = storedSticker('video/webm', 'same-url.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    const video = await screen.findByLabelText(`Стикер ${sticker.name}`) as HTMLVideoElement;
    video.currentTime = 12;
    Object.defineProperty(video, 'duration', { configurable: true, value: 60 });
    const load = spyOn(video, 'load').mockImplementation(() => { video.currentTime = 0; });
    const play = spyOn(video, 'play').mockResolvedValue(undefined);
    fireEvent.play(video);
    mediaError(video, 2);
    await waitFor(() => expect(load.mock.calls.length).toBe(1));
    expect(video.getAttribute('src')).toBe('https://storage.test/a1/archive/same-url.webm');
    expect(video.currentTime).toBe(0);
    fireEvent.loadedMetadata(video);
    expect(video.currentTime).toBe(12);
    expect(play.mock.calls.length).toBe(1);
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  test('дублирующиеся ошибки во время подписи не запускают параллельные запросы', async () => {
    const next = deferred<string>();
    const get = spyOn(apiClient, 'get').mockImplementation(async () => ({
      data: { url: await next.promise, expires_in: 43200 },
    }) as never);
    get.mockResolvedValueOnce({ data: { url: 'https://storage.test/first', expires_in: 43200 } } as never);
    const sticker = storedSticker('video/webm', 'repeat.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    const video = await screen.findByLabelText(`Стикер ${sticker.name}`);
    mediaError(video, null);
    mediaError(video, null);
    expect(get.mock.calls.length).toBe(2);
    await act(async () => { next.resolve('https://storage.test/next'); });
    await waitFor(() => expect(video.getAttribute('src')).toBe('https://storage.test/next'));
    mediaError(video, 4);
    expect(Boolean(screen.queryByText('repeat.webm (недоступно)'))).toBe(true);
    expect(get.mock.calls.length).toBe(2);
  });

  test('успешное воспроизведение разрешает восстановить следующую истёкшую подпись', async () => {
    const sticker = storedSticker('video/webm', 'played.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    const video = await screen.findByLabelText(`Стикер ${sticker.name}`);
    const load = spyOn(video as HTMLVideoElement, 'load').mockImplementation(() => {});
    mediaError(video, 4);
    await waitFor(() => expect(load.mock.calls.length).toBe(1));
    fireEvent.loadedMetadata(video);
    fireEvent.playing(video);
    mediaError(video, 2);
    await waitFor(() => expect(load.mock.calls.length).toBe(2));
    expect(apiClient.get).toHaveBeenCalledTimes(3);
  });

  test('отмена пользователем не запрашивает подпись повторно', async () => {
    const sticker = storedSticker('video/webm', 'aborted.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    const video = await screen.findByLabelText(`Стикер ${sticker.name}`);
    mediaError(video, 1);
    await act(async () => {});
    expect(apiClient.get).toHaveBeenCalledTimes(1);
    expect(Boolean(screen.queryByLabelText(`Стикер ${sticker.name}`))).toBe(true);
  });

  test('ошибка autoplay после восстановления не вызывает повторную подпись', async () => {
    const sticker = storedSticker('video/webm', 'autoplay.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    const video = await screen.findByLabelText(`Стикер ${sticker.name}`) as HTMLVideoElement;
    const load = spyOn(video, 'load').mockImplementation(() => {});
    spyOn(video, 'play').mockRejectedValue(new DOMException('blocked', 'NotAllowedError'));
    fireEvent.play(video);
    mediaError(video, 4);
    await waitFor(() => expect(load.mock.calls.length).toBe(1));
    fireEvent.loadedMetadata(video);
    await act(async () => {});
    expect(apiClient.get).toHaveBeenCalledTimes(2);
    expect(Boolean(screen.queryByText('autoplay.webm (недоступно)'))).toBe(false);
  });

  test('обновление кеша не прерывает проигрывание, новая ссылка применяется на паузе', async () => {
    let signatures = 0;
    spyOn(apiClient, 'get').mockImplementation(async () => ({
      data: { url: `https://storage.test/clip-${++signatures}`, expires_in: 43200 },
    }) as never);
    const sticker = storedSticker('video/webm', 'playing.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    const video = await screen.findByLabelText(`Стикер ${sticker.name}`) as HTMLVideoElement;
    video.currentTime = 8;
    Object.defineProperty(video, 'duration', { configurable: true, value: 60 });
    const load = spyOn(video, 'load').mockImplementation(() => { video.currentTime = 0; });
    fireEvent.play(video);
    await act(async () => {
      await queryClient.refetchQueries({ queryKey: queryKeys.forUser(null).media.all });
    });
    await waitFor(() => expect(signatures).toBe(2));
    expect(video.getAttribute('src')).toBe('https://storage.test/clip-1');
    expect(video.currentTime).toBe(8);
    expect(load.mock.calls.length).toBe(0);
    fireEvent.pause(video);
    await waitFor(() => expect(video.getAttribute('src')).toBe('https://storage.test/clip-2'));
    fireEvent.loadedMetadata(video);
    expect(video.currentTime).toBe(8);
  });

  test('два плеера делят запрос восстановления и не прерывают здорового соседа', async () => {
    const next = deferred<string>();
    const get = spyOn(apiClient, 'get').mockImplementation(async () => ({
      data: { url: await next.promise, expires_in: 43200 },
    }) as never);
    get.mockResolvedValueOnce({ data: { url: 'https://storage.test/first', expires_in: 43200 } } as never);
    const sticker = storedSticker('video/webm', 'shared.webm');
    renderMedia(<>
      <MediaContent agentId="a1" items={[sticker]} />
      <MediaContent agentId="a1" items={[sticker]} />
      <MediaContent agentId="a1" items={[sticker]} />
    </>);
    await waitFor(() => expect(screen.queryAllByLabelText(`Стикер ${sticker.name}`).length).toBe(3));
    const [first, second, healthy] = screen.getAllByLabelText(`Стикер ${sticker.name}`) as HTMLVideoElement[];
    const healthyLoad = spyOn(healthy!, 'load').mockImplementation(() => {});
    fireEvent.play(healthy!);
    mediaError(first!, 4);
    mediaError(second!, 2);
    expect(get.mock.calls.length).toBe(2);
    await act(async () => { next.resolve('https://storage.test/next'); });
    await waitFor(() => expect(first!.getAttribute('src')).toBe('https://storage.test/next'));
    expect(second!.getAttribute('src')).toBe('https://storage.test/next');
    expect(healthy!.getAttribute('src')).toBe('https://storage.test/first');
    expect(healthyLoad.mock.calls.length).toBe(0);
    expect(get.mock.calls.length).toBe(2);
  });

  test('позднее восстановление не трогает новый путь и размонтированный плеер', async () => {
    const next = deferred<string>();
    const get = spyOn(apiClient, 'get').mockImplementation(async () => ({
      data: { url: await next.promise, expires_in: 43200 },
    }) as never);
    get.mockResolvedValueOnce({ data: { url: 'https://storage.test/first', expires_in: 43200 } } as never);
    const sticker = storedSticker('video/webm', 'changed.webm');
    const { rerender } = renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    const old = await screen.findByLabelText(`Стикер ${sticker.name}`) as HTMLVideoElement;
    const load = spyOn(old, 'load').mockImplementation(() => {});
    mediaError(old, 4);
    get.mockResolvedValueOnce({ data: { url: 'https://storage.test/new-path', expires_in: 43200 } } as never);
    rerender(<MediaContent agentId="a1" items={[{ ...sticker, storage_path: 'new/path' }]} />);
    await waitFor(() => expect(screen.queryByLabelText(`Стикер ${sticker.name}`)?.getAttribute('src'))
      .toBe('https://storage.test/new-path'));
    await act(async () => { next.resolve('https://storage.test/stale'); });
    expect(load.mock.calls.length).toBe(0);
    expect(screen.getByLabelText(`Стикер ${sticker.name}`).getAttribute('src')).toBe('https://storage.test/new-path');
  });

  test('ошибка декодирования остаётся окончательной при обновлении кеша', async () => {
    const sticker = storedSticker('video/webm', 'terminal.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    const video = await screen.findByLabelText(`Стикер ${sticker.name}`);
    mediaError(video, 3);
    await act(async () => {
      await queryClient.refetchQueries({ queryKey: queryKeys.forUser(null).media.all });
    });
    expect(Boolean(screen.queryByText('terminal.webm (недоступно)'))).toBe(true);
    expect(Boolean(screen.queryByLabelText(`Стикер ${sticker.name}`))).toBe(false);
  });

  test('неудачное фоновое обновление сохраняет плеер и останавливает таймер повторов', async () => {
    const get = spyOn(apiClient, 'get').mockRejectedValue(new Error('offline'));
    get.mockResolvedValueOnce({ data: { url: 'https://storage.test/cached', expires_in: 0.2 } } as never);
    const sticker = storedSticker('video/webm', 'offline.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    const video = await screen.findByLabelText(`Стикер ${sticker.name}`);
    fireEvent.play(video);
    await waitFor(() => expect(get.mock.calls.length).toBe(2));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 250)); });
    expect(get.mock.calls.length).toBe(2);
    expect(video.getAttribute('src')).toBe('https://storage.test/cached');
    expect(Boolean(screen.queryByText('offline.webm (недоступно)'))).toBe(false);
    mediaError(video, 4);
    await waitFor(() => expect(Boolean(screen.queryByText('offline.webm (недоступно)'))).toBe(true));
    expect(get.mock.calls.length).toBe(3);
  });

  test('после сна вкладки истёкшая ссылка обновляется при фокусе и восстановлении сети', async () => {
    let now = Date.now();
    spyOn(Date, 'now').mockImplementation(() => now);
    let signatures = 0;
    spyOn(apiClient, 'get').mockImplementation(async () => ({
      data: { url: `https://storage.test/clip-${++signatures}`, expires_in: 60 },
    }) as never);
    queryClient.setDefaultOptions({ queries: { refetchOnReconnect: false } });
    const sticker = storedSticker('video/webm', 'sleep.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    await screen.findByLabelText(`Стикер ${sticker.name}`);
    focusManager.setFocused(false);
    now += 61_000;
    await act(async () => { focusManager.setFocused(true); });
    await waitFor(() => expect(signatures).toBe(2));
    onlineManager.setOnline(false);
    now += 61_000;
    await act(async () => { onlineManager.setOnline(true); });
    await waitFor(() => expect(signatures).toBe(3));
  });

  test('обновление подписи работает и в фоновой вкладке', async () => {
    focusManager.setFocused(false);
    let signatures = 0;
    spyOn(apiClient, 'get').mockImplementation(async () => ({
      data: { url: `https://storage.test/clip-${++signatures}`, expires_in: 0.2 },
    }) as never);
    const sticker = storedSticker('video/webm', 'background.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    await screen.findByLabelText(`Стикер ${sticker.name}`);
    await waitFor(() => expect(signatures).toBe(2));
  });

  test('TTL отсчитывается с начала запроса, а не с получения ответа', async () => {
    let now = Date.now();
    const requestedAt = now;
    spyOn(Date, 'now').mockImplementation(() => now);
    const response = deferred<string>();
    spyOn(apiClient, 'get').mockImplementation(async () => ({
      data: { url: await response.promise, expires_in: 60 },
    }) as never);
    const sticker = storedSticker('video/webm', 'slow-sign.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    now += 30_000;
    await act(async () => { response.resolve('https://storage.test/slow'); });
    await screen.findByLabelText(`Стикер ${sticker.name}`);
    const cached = queryClient.getQueryData<{ renewAt: number }>(
      queryKeys.forUser(null).media.link('a1', sticker.storage_path!),
    );
    expect(cached?.renewAt).toBe(requestedAt + 54_000);
  });

  test('повторное монтирование использует свежий кеш, но обновляет просроченную подпись', async () => {
    let now = Date.now();
    spyOn(Date, 'now').mockImplementation(() => now);
    let signatures = 0;
    spyOn(apiClient, 'get').mockImplementation(async () => ({
      data: { url: `https://storage.test/clip-${++signatures}`, expires_in: 60 },
    }) as never);
    const sticker = storedSticker('video/webm', 'remount.webm');
    const first = renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    await screen.findByLabelText(`Стикер ${sticker.name}`);
    first.unmount();
    const fresh = renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    await act(async () => {});
    expect(signatures).toBe(1);
    fresh.unmount();
    now += 61_000;
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    await waitFor(() => expect(signatures).toBe(2));
  });

  test('декодирование, сломавшееся во время подписи, не оживает после её получения', async () => {
    const next = deferred<string>();
    const get = spyOn(apiClient, 'get').mockImplementation(async () => ({
      data: { url: await next.promise, expires_in: 43200 },
    }) as never);
    get.mockResolvedValueOnce({ data: { url: 'https://storage.test/first', expires_in: 43200 } } as never);
    const sticker = storedSticker('video/webm', 'late-decode.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    const video = await screen.findByLabelText(`Стикер ${sticker.name}`) as HTMLVideoElement;
    const load = spyOn(video, 'load').mockImplementation(() => {});
    mediaError(video, 2);
    mediaError(video, 3);
    await act(async () => { next.resolve('https://storage.test/late'); });
    expect(Boolean(screen.queryByText('late-decode.webm (недоступно)'))).toBe(true);
    expect(load.mock.calls.length).toBe(0);
  });

  test('ошибка лайтбокса не переносится на следующее изображение', async () => {
    const first = storedSticker('image/webp', 'first.webp');
    const second = storedSticker('image/webp', 'second.webp');
    renderMedia(<MediaContent agentId="a1" items={[first, second]} />);
    await screen.findByRole('img', { name: first.name });
    fireEvent.click(screen.getByRole('button', { name: first.name }));
    const dialog = screen.getByRole('dialog');
    const brokenImage = await within(dialog).findByRole('img', { name: first.name });
    const previousUrl = brokenImage.getAttribute('src');
    fireEvent.error(brokenImage);
    expect(within(dialog).getByText('first.webp (недоступно)')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Следующее изображение'));
    // Флеш микротасков внутри act: у нового изображения резолвится загрузка,
    // и без этого обновление состояния выпадает за пределы act.
    await act(async () => {});
    await waitFor(() => {
      const nextImage = within(dialog).getByRole('img', { name: second.name });
      expect(nextImage.getAttribute('src')).not.toBe(previousUrl);
    });
    expect(within(dialog).queryByText('first.webp (недоступно)')).toBeNull();
  });

  test('после смены storage_path превью восстанавливается', async () => {
    const sticker = storedSticker('image/webp', 'static.webp');
    const { rerender } = renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    fireEvent.error(await screen.findByRole('img', { name: sticker.name }));
    rerender(
      <MediaContent
        agentId="a1"
        items={[{ ...sticker, storage_path: 'a1/new/static.webp' }]}
      />,
    );
    expect(await screen.findByRole('img', { name: sticker.name })).toBeTruthy();
    expect(screen.queryByText('static.webp (недоступно)')).toBeNull();
  });

  test('HTTP-ошибка оставляет понятную плашку', async () => {
    spyOn(apiClient, 'get').mockRejectedValue(new Error('missing archive'));
    const sticker = storedSticker('image/webp', 'missing.webp');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    expect(await screen.findByText('missing.webp (недоступно)')).toBeTruthy();
    expect(screen.queryByRole('img')).toBeNull();
  });

  test('MIME с параметрами классифицируется как WebP', async () => {
    const sticker = storedSticker(' IMAGE/WEBP ; charset=binary', 'static.webp');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    expect(await screen.findByRole('img', { name: sticker.name })).toBeTruthy();
  });

  test('object URL картинки освобождается при размонтировании', async () => {
    const sticker = storedSticker('image/webp', 'static.webp');
    const { unmount } = renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    const image = await screen.findByRole('img', { name: sticker.name });
    const url = image.getAttribute('src');
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(url);
  });

  test('кружок из Telegram играет как видео', async () => {
    const round: MediaItem = {
      kind: 'round',
      name: 'round.mp4',
      mime_type: 'video/mp4',
      size: 2048,
      storage_path: 'a1/archive/round.mp4',
    };
    renderMedia(<MediaContent agentId="a1" items={[round]} />);
    const video = await screen.findByLabelText(round.name);
    expect(video.tagName).toBe('VIDEO');
    expect(video.hasAttribute('loop')).toBe(false);
    expect(video.getAttribute('src')).toBe('https://storage.test/a1/archive/round.mp4');
    expect(apiClient.get).toHaveBeenCalledWith('/agents/a1/media-link/a1/archive/round.mp4', { accountScope: undefined });
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  test('голосовое играет как аудио', async () => {
    const voice: MediaItem = {
      kind: 'voice',
      name: 'voice.ogg',
      mime_type: 'audio/ogg',
      size: 2048,
      storage_path: 'a1/archive/voice.ogg',
    };
    const { container } = renderMedia(<MediaContent agentId="a1" items={[voice]} />);
    await waitFor(() => {
      expect(container.querySelector('audio')?.getAttribute('src')).toBe(
        'https://storage.test/a1/archive/voice.ogg',
      );
    });
    expect(container.querySelector('audio')?.hasAttribute('controls')).toBe(true);
    expect(apiClient.get).toHaveBeenCalledWith('/agents/a1/media-link/a1/archive/voice.ogg', { accountScope: undefined });
  });

  test('обычное видео из Telegram (doc + video/mp4) играет как видео', async () => {
    const clip: MediaItem = {
      kind: 'doc',
      name: 'clip.mp4',
      mime_type: 'video/mp4',
      size: 2048,
      storage_path: 'a1/archive/clip.mp4',
    };
    renderMedia(<MediaContent agentId="a1" items={[clip]} />);
    const video = await screen.findByLabelText(clip.name);
    expect(video.tagName).toBe('VIDEO');
    expect(video.getAttribute('src')).toBe('https://storage.test/a1/archive/clip.mp4');
    expect(apiClient.get).toHaveBeenCalledWith('/agents/a1/media-link/a1/archive/clip.mp4', { accountScope: undefined });
    expect(screen.queryByRole('link', { name: /clip\.mp4/ })).toBeNull();
  });

  test('документ с PDF остаётся ссылкой на скачивание', async () => {
    const doc: MediaItem = {
      kind: 'doc',
      name: 'report.pdf',
      mime_type: 'application/pdf',
      size: 2048,
      storage_path: 'a1/archive/report.pdf',
    };
    renderMedia(<MediaContent agentId="a1" items={[doc]} />);
    const link = await screen.findByRole('link', { name: /report\.pdf/ });
    expect(link.getAttribute('href')).toBe('blob:media-1');
    expect(apiClient.get).toHaveBeenCalledWith('/agents/a1/media/a1/archive/report.pdf', {
      responseType: 'blob',
    });
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  test('ошибка подписи ссылки показывает плашку «недоступно»', async () => {
    spyOn(apiClient, 'get').mockRejectedValue(new Error('sign failed'));
    const sticker = storedSticker('video/webm', 'broken.webm');
    renderMedia(<MediaContent agentId="a1" items={[sticker]} />);
    expect(await screen.findByText('broken.webm (недоступно)')).toBeTruthy();
    expect(screen.queryByLabelText(`Стикер ${sticker.name}`)).toBeNull();
  });
});
