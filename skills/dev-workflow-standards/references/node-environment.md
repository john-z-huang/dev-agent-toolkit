# Node.js 代码格式化与静态检查

适用于 Node.js 管理的 JavaScript 和 TypeScript 项目。先核对目标包的 `package.json`、包管理器、锁文件及 Node.js 版本约束。workspace 项目同时核对成员归属，从项目规定的根目录或成员目录执行命令。沿用现有脚本、配置和锁定策略。

## 开发指令与命令

在项目开发指令中记录运行目录、检查范围和命令。Prettier 负责写入格式及只读格式检查，ESLint 负责静态规则检查。TypeScript 项目同时记录类型检查命令。Code Agent 必须调用项目配置的 Prettier 命令处理缩进、空白、折行、引号等纯格式变更。禁止用 Edit、补丁或其他编辑工具手工调整格式。命令无法运行时，先核对运行时和项目开发依赖，仍无法运行则报告阻塞。

下列示例从使用 npm 的项目根目录运行。使用 pnpm、Yarn 或其他包管理器时，用该项目自己的依赖安装、脚本执行和锁文件更新方式。示例采用 ESLint 10 的 flat config，要求 Node.js 20.19+（20.x）、22.13+（22.x）或 24+。已有项目应按其 Node.js 和插件版本选择兼容的工具与配置。 [ESLint 运行时要求](https://eslint.org/docs/latest/use/getting-started#prerequisites) · [typescript-eslint 版本要求](https://typescript-eslint.io/users/dependency-versions/)

### 开发依赖与脚本

将所需工具声明为项目开发依赖，更新项目锁文件。npm 项目可运行以下命令，第三条用于需要引入 TypeScript 编译器和 ESLint 集成的项目。已有兼容的 TypeScript 版本时保留现有版本，只补齐缺失的依赖。

```bash
/bin/bash -c 'npm install --save-dev eslint@10 @eslint/js@10 globals eslint-config-prettier'
/bin/bash -c 'npm install --save-dev --save-exact prettier@3'
/bin/bash -c 'npm install --save-dev typescript@5.9 typescript-eslint@8'
```

合并以下字段到 `package.json` 的 `scripts`，保留已有脚本。

```json
{
  "scripts": {
    "format": "prettier --write .",
    "format:check": "prettier --check .",
    "lint": "eslint ."
  }
}
```

对于使用单个 `tsconfig.json` 的 TypeScript 项目，可在 `scripts` 中添加 `"typecheck": "tsc --noEmit --project tsconfig.json"`。使用项目引用、框架或既有类型检查入口时，沿用对应的命令和配置。 [TypeScript `noEmit`](https://www.typescriptlang.org/tsconfig/noEmit.html)

```bash
/bin/bash -c 'npm run format'
/bin/bash -c 'npm run format:check'
/bin/bash -c 'npm run lint'
```

TypeScript 项目另运行 `/bin/bash -c 'npm run typecheck'`。`format` 写入项目内 Prettier 支持且未忽略的文件，其余脚本检查并通过退出状态报告结果。只格式化指定文件时，可在已经同步本地依赖的 npm 项目中直接传入路径，避免给带 `.` 的脚本继续追加参数。

```bash
/bin/bash -c 'npm exec -- prettier --write -- "$@"' _ 'src/path with spaces.ts'
```

### `eslint.config.mjs`（JavaScript）

纯 JavaScript 项目使用以下配置。示例覆盖 Node.js 源码，`.js` 按 ES module 处理，`.cjs` 按 CommonJS 处理。如果项目将 `.js` 用作 CommonJS，增加匹配相应 `.js` 文件的 `sourceType: "commonjs"` 配置。浏览器、测试和框架的全局变量或解析规则按文件范围配置。

```javascript
import js from "@eslint/js";
import prettier from "eslint-config-prettier/flat";
import { defineConfig, globalIgnores } from "eslint/config";
import globals from "globals";

export default defineConfig(
  globalIgnores(["**/dist/", "**/build/", "**/coverage/"]),
  {
    files: ["**/*.{js,mjs,cjs}"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.nodeBuiltin },
  },
  prettier,
);
```

### `eslint.config.mjs`（TypeScript 与混合项目）

使用下面的配置替代纯 JavaScript 示例。TypeScript 的规则只应用于 TypeScript 文件，JavaScript 仍使用 ESLint 推荐规则。两个示例都把 `eslint-config-prettier` 放在规则之后，停用与 Prettier 冲突的 ESLint 规则。 [ESLint 配置](https://eslint.org/docs/latest/use/configure/configuration-files) · [typescript-eslint 配置](https://typescript-eslint.io/getting-started/) · [eslint-config-prettier](https://github.com/prettier/eslint-config-prettier)

```javascript
import js from "@eslint/js";
import prettier from "eslint-config-prettier/flat";
import { defineConfig, globalIgnores } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig(
  globalIgnores(["**/dist/", "**/build/", "**/coverage/"]),
  {
    files: ["**/*.{js,mjs,cjs,ts,mts,cts,tsx}"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.nodeBuiltin },
  },
  {
    files: ["**/*.{ts,mts,cts,tsx}"],
    extends: [tseslint.configs.recommended],
  },
  prettier,
);
```

### `.prettierrc.json` 与 `.prettierignore`

JavaScript 和 TypeScript 项目均可使用以下 `.prettierrc.json`。项目已有 `package.json` 的 `prettier` 字段或独立配置时，在现有位置维护格式选项。配置值沿用项目约定。 [Prettier 配置](https://prettier.io/docs/configuration)

```json
{
  "printWidth": 88,
  "singleQuote": false,
  "trailingComma": "all"
}
```

在 `.prettierignore` 中按实际情况排除生成产物和锁文件。ESLint 的生成目录排除由其自身配置管理。 [Prettier 忽略规则](https://prettier.io/docs/ignore/)

```text
dist/
build/
coverage/
package-lock.json
pnpm-lock.yaml
yarn.lock
bun.lock
```
