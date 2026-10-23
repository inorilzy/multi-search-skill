import { mountDiagnostics } from './diagnostics.js';
import { mountInstall } from './install.js';
import { mountSkill } from './skill.js';
import { mountSources } from './sources.js';
import { mountSettings } from './settings.js';
import { mountScrape } from './scrape.js';
export const pages = [
  { id: 'diagnostics', label: '概览与测试', number: '01', mount: mountDiagnostics },
  { id: 'install', label: '安装 CLI', number: '02', mount: mountInstall },
  { id: 'skill', label: 'Claude Code 技能', number: '03', mount: mountSkill },
  { id: 'sources', label: '搜索源与凭据', number: '04', mount: mountSources },
  { id: 'settings', label: '搜索设置', number: '05', mount: mountSettings },
  { id: 'scrape', label: '抓取设置', number: '06', mount: mountScrape },
];
