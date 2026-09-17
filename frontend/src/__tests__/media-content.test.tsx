import { describe, expect, test } from 'bun:test';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MediaContent } from '@/components/activity/MediaContent';
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
