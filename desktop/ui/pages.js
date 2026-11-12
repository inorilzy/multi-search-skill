import { mountDiagnostics } from './diagnostics.js';
import { mountInstall } from './install.js';
import { mountSkill } from './skill.js';
import { mountSources } from './sources.js';
import { mountSettings } from './settings.js';
import { mountScrape } from './scrape.js';
import { mountCookies } from './cookies.js';
import { mountUsage } from './usage.js';

// Every entry is `{ id, label, number, mount }`; `tests/test_docs_sync.py` reads this table to keep
// the README in sync, so keep the regex-friendly literal shape (`id:` then `label:` then `number:`).
// The order here is the sidebar order, and each page renders its own number in the eyebrow.
export const pages = [
  { id: 'diagnostics', label: '概览与测试', number: '01', mount: mountDiagnostics },
  { id: 'install', label: '安装 CLI', number: '02', mount: mountInstall },
  { id: 'skill', label: 'Agent Skill', number: '03', mount: mountSkill },
  { id: 'sources', label: '服务商', number: '04', mount: mountSources },
  { id: 'usage', label: '用量', number: '05', mount: mountUsage },
  { id: 'settings', label: '搜索设置', number: '06', mount: mountSettings },
  { id: 'scrape', label: '抓取设置', number: '07', mount: mountScrape },
  { id: 'cookies', label: 'Cookie 导入', number: '08', mount: mountCookies },
];
