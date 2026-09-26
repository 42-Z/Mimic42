import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-geist-sans)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-geist-mono)', 'monospace'],
        display: ['var(--font-display)', 'system-ui', 'sans-serif'],
      },
      colors: {
        // Base palette — dark terminal aesthetic
        void: {
          50:  '#f0f0f2',
          100: '#e0e0e5',
          200: '#c0c0cc',
          300: '#9090a0',
          400: '#606075',
          500: '#3a3a4a',
          600: '#252535',
          700: '#1a1a28',
          800: '#121220',
          900: '#0a0a16',
          950: '#05050e',
        },
        // Electric blue accent
        plasma: {
          50:  '#e8f4ff',
          100: '#d0e9ff',
          200: '#a8d4ff',
          300: '#70b8ff',
          400: '#3d9bff',
          500: '#1a7fff',
          600: '#0062e6',
          700: '#004dbf',
          800: '#003d99',
          900: '#002d73',
          950: '#001847',
        },
        // Neon green status
        neon: {
          50:  '#f0fff4',
          100: '#dcffe8',
          200: '#b3ffd0',
          300: '#6effb0',
          400: '#24f98a',
          500: '#00e070',
          600: '#00b85c',
          700: '#008f48',
          800: '#006b37',
          900: '#004f2a',
          950: '#00291a',
        },
        // Warning amber
        amber: {
          50:  '#fffbeb',
          100: '#fef3c7',
          200: '#fde68a',
          300: '#fcd34d',
          400: '#fbbf24',
          500: '#f59e0b',
          600: '#d97706',
          700: '#b45309',
          800: '#92400e',
          900: '#78350f',
          950: '#451a03',
        },
        // Error red
        crimson: {
          50:  '#fff1f2',
          100: '#ffe4e6',
          200: '#fecdd3',
          300: '#fda4af',
          400: '#fb7185',
          500: '#f43f5e',
          600: '#e11d48',
          700: '#be123c',
          800: '#9f1239',
          900: '#881337',
          950: '#4c0519',
        },
        // shadcn semantic tokens (CSS vars hold RGB triplets → alpha-ready)
        background: 'rgb(var(--background) / <alpha-value>)',
        foreground: 'rgb(var(--foreground) / <alpha-value>)',
        card: { DEFAULT: 'rgb(var(--card) / <alpha-value>)', foreground: 'rgb(var(--card-foreground) / <alpha-value>)' },
        popover: { DEFAULT: 'rgb(var(--popover) / <alpha-value>)', foreground: 'rgb(var(--popover-foreground) / <alpha-value>)' },
        primary: { DEFAULT: 'rgb(var(--primary) / <alpha-value>)', foreground: 'rgb(var(--primary-foreground) / <alpha-value>)' },
        secondary: { DEFAULT: 'rgb(var(--secondary) / <alpha-value>)', foreground: 'rgb(var(--secondary-foreground) / <alpha-value>)' },
        muted: { DEFAULT: 'rgb(var(--muted) / <alpha-value>)', foreground: 'rgb(var(--muted-foreground) / <alpha-value>)' },
        accent: { DEFAULT: 'rgb(var(--accent) / <alpha-value>)', foreground: 'rgb(var(--accent-foreground) / <alpha-value>)' },
        destructive: { DEFAULT: 'rgb(var(--destructive) / <alpha-value>)', foreground: 'rgb(var(--destructive-foreground) / <alpha-value>)' },
        success: { DEFAULT: 'rgb(var(--success) / <alpha-value>)', foreground: 'rgb(var(--success-foreground) / <alpha-value>)' },
        warning: 'rgb(var(--warning) / <alpha-value>)',
        border: 'rgb(var(--border) / <alpha-value>)',
        input: 'rgb(var(--input) / <alpha-value>)',
        ring: 'rgb(var(--ring) / <alpha-value>)',
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      backgroundImage: {
        'grid-pattern': `
          linear-gradient(rgba(26, 127, 255, 0.03) 1px, transparent 1px),
          linear-gradient(90deg, rgba(26, 127, 255, 0.03) 1px, transparent 1px)
        `,
        'noise': "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.05'/%3E%3C/svg%3E\")",
        'plasma-glow': 'radial-gradient(ellipse at top, rgba(26, 127, 255, 0.15) 0%, transparent 60%)',
        'agent-card': 'linear-gradient(135deg, rgba(26, 26, 40, 0.8) 0%, rgba(18, 18, 32, 0.9) 100%)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'blink': 'blink 1.2s step-end infinite',
        'slide-in-right': 'slideInRight 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
        'slide-in-up': 'slideInUp 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
        'fade-in': 'fadeIn 0.2s ease-out',
        'shimmer': 'shimmer 2s linear infinite',
        'scan': 'scan 8s linear infinite',
        'float': 'float 6s ease-in-out infinite',
        'status-pulse': 'statusPulse 2s ease-in-out infinite',
      },
      keyframes: {
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        slideInRight: {
          '0%': { transform: 'translateX(100%)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        slideInUp: {
          '0%': { transform: 'translateY(20px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-1000px 0' },
          '100%': { backgroundPosition: '1000px 0' },
        },
        scan: {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(100vh)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-10px)' },
        },
        statusPulse: {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%': { opacity: '0.7', transform: 'scale(1.1)' },
        },
      },
      boxShadow: {
        'plasma': '0 0 20px rgba(26, 127, 255, 0.3), 0 0 60px rgba(26, 127, 255, 0.1)',
        'plasma-sm': '0 0 10px rgba(26, 127, 255, 0.2)',
        'neon': '0 0 20px rgba(0, 224, 112, 0.3)',
        'neon-sm': '0 0 10px rgba(0, 224, 112, 0.2)',
        'crimson': '0 0 20px rgba(244, 63, 94, 0.3)',
        'void': '0 4px 30px rgba(0, 0, 0, 0.5)',
        'void-lg': '0 8px 60px rgba(0, 0, 0, 0.7)',
        'inner-glow': 'inset 0 1px 0 rgba(255, 255, 255, 0.05)',
      },
      backdropBlur: {
        'xs': '2px',
      },
      borderColor: {
        DEFAULT: 'rgba(96, 96, 117, 0.2)',
      },
      spacing: {
        '13': '3.25rem',
        '18': '4.5rem',
        '22': '5.5rem',
        '68': '17rem',
        '72': '18rem',
        '80': '20rem',
      },
      screens: {
        '3xl': '1920px',
      },
      transitionTimingFunction: {
        'spring': 'cubic-bezier(0.16, 1, 0.3, 1)',
        'smooth': 'cubic-bezier(0.4, 0, 0.2, 1)',
      },
    },
  },
  plugins: [],
};

export default config;
