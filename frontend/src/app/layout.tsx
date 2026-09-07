import type { Metadata, Viewport } from 'next';
import './globals.css';
import { Providers } from './providers';

export const metadata: Metadata = {
  title: { default: 'Mimic42', template: '%s — Mimic42' },
  description: 'AI-агент, имитирующий человека в Telegram',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#05050e',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className="dark">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
