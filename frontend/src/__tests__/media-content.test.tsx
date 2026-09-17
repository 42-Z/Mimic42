import { describe, expect, test } from 'bun:test';
import { render, screen, within } from '@testing-library/react';
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
});
