import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import { notionTheme } from './theme/notionTheme'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: notionTheme.accent,
          colorInfo: notionTheme.info,
          colorSuccess: notionTheme.success,
          colorWarning: notionTheme.orange,
          colorError: notionTheme.danger,
          colorText: notionTheme.text,
          colorTextSecondary: notionTheme.textSecondary,
          colorTextTertiary: notionTheme.textTertiary,
          colorBorder: notionTheme.border,
          colorBorderSecondary: notionTheme.borderStrong,
          colorBgContainer: notionTheme.surface,
          colorBgElevated: notionTheme.surface,
          colorBgLayout: notionTheme.bg,
          colorFillAlter: notionTheme.surfaceAlt,
          colorFillSecondary: notionTheme.surfaceHover,
          borderRadius: 8,
          fontFamily:
            'ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
        },
      }}
    >
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ConfigProvider>
  </StrictMode>,
)
