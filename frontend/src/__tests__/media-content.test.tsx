import { afterEach, beforeEach, describe, expect, mock, spyOn, test } from 'bun:test';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MediaContent } from '@/components/activity/MediaContent';
import { apiClient } from '@/lib/api';
import type { MediaItem } from '@/types';

function item(kind: MediaItem['kind'], name: string): MediaItem {
  return {
    kind,
    name,
    mime_type: 'image/jpeg',
    size: 1024,
    storage_path: null,
  };
}

describe('MediaContent', () => {
  test('несколько картинок идут в ряд в отдельной галерее', () => {
    render(
      <MediaContent
        agentId="a1"
        items={[item('photo', '1.jpeg'), item('photo', '2.jpeg'), item('photo', '3.jpeg')]}
      />,
    );
    const gallery = screen.getByTestId('media-gallery');
    expect(within(gallery).getAllByRole('button')).toHaveLength(3);
  });

  test('одна картинка рендерится как раньше, без галереи', () => {
    render(<MediaContent agentId="a1" items={[item('photo', 'solo.jpeg')]} />);
    expect(screen.queryByTestId('media-gallery')).toBeNull();
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  test('не-картинки не попадают в галерею', () => {
    render(
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
    render(
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
    spyOn(apiClient, 'get').mockResolvedValue({ data: new Blob(['test-media']) });
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
    render(<MediaContent agentId="a1" items={[sticker]} />);
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
    render(<MediaContent agentId="a1" items={[sticker]} />);
    const video = await screen.findByLabelText(`Стикер ${sticker.name}`);
    expect(video.tagName).toBe('VIDEO');
    expect(video.hasAttribute('controls')).toBe(true);
    expect(video.hasAttribute('loop')).toBe(true);
    expect(video.hasAttribute('playsinline')).toBe(true);
    expect((video as HTMLVideoElement).muted).toBe(true);
    expect(video.hasAttribute('autoplay')).toBe(false);
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.queryByTestId('media-gallery')).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('TGS сразу показывает плашку без скачивания', () => {
    const sticker = storedSticker('application/x-tgsticker', 'animation.tgs');
    render(<MediaContent agentId="a1" items={[sticker]} />);
    expect(screen.getByText('animation.tgs (анимированный стикер)')).toBeTruthy();
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  test('неизвестный MIME стикера не создаёт сломанный img', () => {
    const sticker = storedSticker('application/octet-stream', 'legacy.sticker');
    render(<MediaContent agentId="a1" items={[sticker]} />);
    expect(screen.getByText('legacy.sticker (предпросмотр недоступен)')).toBeTruthy();
    expect(screen.queryByRole('img')).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  test('пустой MIME стикера безопасно заменяется плашкой', () => {
    render(<MediaContent agentId="a1" items={[storedSticker('', 'legacy.sticker')]} />);
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
    render(
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
    render(<MediaContent agentId="a1" items={[sticker]} />);
    fireEvent.error(await screen.findByRole('img', { name: sticker.name }));
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.getByText('legacy.webp (недоступно)')).toBeTruthy();
  });

  test('ошибка декодирования WebM заменяет video плашкой', async () => {
    const sticker = storedSticker('video/webm', 'broken.webm');
    render(<MediaContent agentId="a1" items={[sticker]} />);
    fireEvent.error(await screen.findByLabelText(`Стикер ${sticker.name}`));
    expect(screen.queryByLabelText(`Стикер ${sticker.name}`)).toBeNull();
    expect(screen.getByText('broken.webm (недоступно)')).toBeTruthy();
  });

  test('ошибка лайтбокса не переносится на следующее изображение', async () => {
    const first = storedSticker('image/webp', 'first.webp');
    const second = storedSticker('image/webp', 'second.webp');
    render(<MediaContent agentId="a1" items={[first, second]} />);
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
    const { rerender } = render(<MediaContent agentId="a1" items={[sticker]} />);
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
    render(<MediaContent agentId="a1" items={[sticker]} />);
    expect(await screen.findByText('missing.webp (недоступно)')).toBeTruthy();
    expect(screen.queryByRole('img')).toBeNull();
  });

  test('MIME с параметрами классифицируется как WebP', async () => {
    const sticker = storedSticker(' IMAGE/WEBP ; charset=binary', 'static.webp');
    render(<MediaContent agentId="a1" items={[sticker]} />);
    expect(await screen.findByRole('img', { name: sticker.name })).toBeTruthy();
  });

  test('object URL освобождается при размонтировании', async () => {
    const sticker = storedSticker('video/webm', 'video.webm');
    const { unmount } = render(<MediaContent agentId="a1" items={[sticker]} />);
    const video = await screen.findByLabelText(`Стикер ${sticker.name}`);
    const url = video.getAttribute('src');
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(url);
  });
});
