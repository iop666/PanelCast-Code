# PanelCast 复核清单（REVIEW-MANIFEST）

本仓库是 PanelCast 的**唯一公开仓库**：代码、文档、测试、审计证据都在同一处。
原两个镜像已合并到此仓库并删除/改名：

| 项 | 值 |
| --- | --- |
| 本地代码 HEAD | `f24c78a` — P0-01：BEAT-MAPPING-REVIEW-FIX：b24/b29 拆分 + 审计来源同步 |
| 上一提交 | `fd22426` — 清单：最终状态同步后的 122 文件哈希 |
| 更早基线 | `9ca6c63` — P0-01：最终状态同步（双 PASS）；`4f618cf` — P0-01：seg_0014 来源范围同步 259–277；`38de088` — 清单：BEAT-MAPPING-FIX 产物哈希；`2fd94f3` — P0-01-CH01-BEAT-MAPPING-FIX：边界修正 + b23/b34 拆分 + 哈希重绑；`88a7352` — 清单；`d5a9991` — 文档：P0-01 复核状态闭环 + 页级映射说明；`4e5f8c2` — P0-01 样张证据同步；`c460019` — 清单；`7aa405e` — P0-01 样张复核修订；`ff02eb5` — 清单；`0b3861c` — P0-REVIEW-10；`7a92652` — P0-REVIEW-09；`69f2913` — P0-REVIEW-08；`d5dfd6c` — 清单：384 tests；`12e8c3f` — P0-REVIEW-07 |
| 原文档镜像（已删除） | `iop666/ChatGPT-Read` @ `61b685c` |
| 原代码审查镜像（已改名并覆盖） | `iop666/PanelCast-Code-Review` @ `38c5bed` → `iop666/PanelCast-Code` |
| 纳入文件数 | 122 |
| 全量测试（本机） | `Ran 430 tests` / `OK (skipped=2)` |
| 跳过项（本机） | 2 项：缺真实 EPUB、缺真实 MOBI（见下节） |
| 索引侧 CRLF blob | `git ls-files --eol \| grep -c "i/crlf"` → `0` |

## 测试环境与跳过项

**同一份代码在不同环境下的跳过数不同，这是环境差异，不是功能失败。**
本清单记录的是本机（Windows / Python 3.14.6 / 带 `.git` / 装了 ffmpeg）的结果。

| 环境 | 结果 | 跳过构成 |
| --- | --- | --- |
| 本机（完整仓库） | `430 / skipped=2` | 缺真实 EPUB 1、缺真实 MOBI 1 |
| ZIP 解压（无 `.git`、无 ffmpeg） | 本轮未复跑 | P0-REVIEW-07 时为 `384 / skipped=8`。P0-REVIEW-08/09/10 新增 46 例未在该环境实测；其中 3 条 Schema/Linter 对照测试依赖可选 `jsonschema`，缺失时会另加跳过 |

**2026-11-18 提交 `f24c78a` 后复跑（BEAT-MAPPING-REVIEW-FIX）**：`Ran 430 tests / OK (skipped=2)`；
`test_fresh_clone_matches_working_tree` 实际执行并通过（此前因两个哈希绑定文件
未提交而在工作区跳过；该跳过不代表通过）。

本机的两个跳过项逐条列出（不是笼统归因于 ffmpeg）：

- `test_epub.TestEpubParsing.test_real_epub_six_chapters` — `real EPUB not present`
- `test_mobi.TestMobiIngest.test_real_mobi_169_pages` — `real MOBI not present`

**跳过不等于通过。** 这两个用例验证真实素材解析（169 / 167 页），
缺版权素材时无法执行，所以不计入已验证。同理，ZIP 环境因缺 `.git`
跳过的 3 个换行测试、因缺 ffmpeg 跳过的 3 个渲染测试，
也不能用本机的通过结果代替。

## 从 ChatGPT-Read 迁移的内容

该仓库的全部 13 个文件都能在本仓库找到对应内容：

| 原路径 | 本仓库路径 |
| --- | --- |
| `README.md`（索引页） | `docs/REVIEW-INDEX.md`（链接已按真实目录修正） |
| `panelcast/PROJECT-README.md` | `README.md` |
| `panelcast/ROADMAP.md` | `docs/ROADMAP.md` |
| `panelcast/PROJECT-MAP.md` | `docs/PROJECT-MAP.md` |
| `panelcast/P0-execution-plan.md` | `docs/tasks/P0-execution-plan.md` |
| `panelcast/WORKFLOW-*.md` | `docs/WORKFLOW-*.md` |
| `panelcast/schemas/script-audit.schema.json` | `docs/schemas/script-audit.schema.json` |
| `panelcast/m1/audit/*.md` | `m1/audit/*.md` |
| `panelcast/m1/v1/ch01/novel_ref.json` | `m1/v1/ch01/work/novel_ref.json` |
| `panelcast/m1/v1/ch01/script-audit.json` | `m1/v1/ch01/work/script-audit.json` |
| `.gitattributes` | `.gitattributes` |

索引页里两个样张链接原先写成 `m1/v1/ch01/novel_ref.json`，
与真实路径 `m1/v1/ch01/work/novel_ref.json` 不一致，已按本地实际结构修正。

## 逐文件 SHA-256

口径：已提交文件按 **git 入库字节** 计算（`git show HEAD:<path>`），
不是工作区字节——工作区里 `__main__.py` / `verify.py` 是 `.gitattributes`
生效前检出的 CRLF，直接按工作区算会与任何平台的新克隆对不上。
`blob(10)` 是 `sha1("blob <len>\0" + bytes)` 的前 10 位，可直接与
GitHub Git Tree API 返回的 sha 比对。

| 文件 | 字节 | SHA-256 | blob(10) | 来源 |
| --- | ---: | --- | --- | --- |
| `.gitattributes` | 865 | `a65264297f26763de8d2cef587c5196c5034748e6583e7773b9c713671ba30ec` | `a1a9971cd2` | HEAD |
| `.gitignore` | 1500 | `1e6ad7aad0b46f691bfd8c7b04eb6f07b7c7a9bacefe4b9381ca140f0f8a6f30` | `7d513943c2` | HEAD |
| `README.md` | 6474 | `40c6a91ac22e3b4f6505ef4497f1fc3cc683e226012365c235d7cfc0d6f35cbc` | `72ce08205a` | HEAD |
| `docs/ADR-001-source-ingestion.md` | 6631 | `bb382d750b82d80145455121c61c481333bd39c6e94b5f224f054628025fba44` | `cb9a9f4cff` | HEAD |
| `docs/ADR-002-m1-render-stack.md` | 4469 | `43acdc4882f671d5faec9027caa23ac8e89faf08c28d772cbc752618b5499fd5` | `6777f04036` | HEAD |
| `docs/PROJECT-MAP.md` | 23762 | `eaad5166076b694adcb077bf70b5a7e96ecc8218c4b2cb199b6179f218977b86` | `eaad516607` | HEAD |
| `docs/REVIEW-INDEX.md` | 16497 | `79b9f07e1a98df5bfcca647f8e7589d38eef3a0a8ca5e045312c8afae81d947a` | `79b9f07e1a` | HEAD |
| `docs/ROADMAP.md` | 32648 | `82e26492ea139977b49dd7bd3f091265a30f1a8506841388d6c4d76adf033e96` | `82e26492ea` | HEAD |
| `docs/WORKFLOW-v1-vertical-manga-narration.md` | 126802 | `0cfc1159c6cec5e65de3c94ed0ae97aa3497978fdba00319789ca2e50559258e` | `0cfc1159c6` | HEAD |
| `docs/schemas/page-profile.schema.json` | 7339 | `7f627622a0e8b65dd9f6c3fbbc9084be72d828fca1d75d37a4a653f0b425427d` | `d0ea1ee32a` | HEAD |
| `docs/schemas/script-audit.schema.json` | 12283 | `dab89397a38d75cd9e53a3a9b71dc1da95423fc60aa9ccf6674a546351072144` | `33975dc4b1` | HEAD |
| `docs/tasks/M0-content-validation.md` | 10621 | `585e55374ac111baa4d87849db7a29b77fcb9af4785f4eee1fb37c627799085f` | `11056e5ad3` | HEAD |
| `docs/tasks/M1-minimal-loop.md` | 11666 | `46ebea01efa71267f0d38eb76bad8da16d876a6dda958937aade6af97e69d988` | `dbc7d683aa` | HEAD |
| `docs/tasks/P0-execution-plan.md` | 45860 | `2b9a8b46042665c822a228574e10e12c199d6348b124c63e54438f8b3851dfee` | `2b9a8b4604` | HEAD |
| `docs/tasks/TASK-002-ingest-hardening.md` | 7250 | `8dcb085aa23d392c0ab225ca16c1a3635fed498f513acc8a06ddc64a2959e447` | `3ae7359883` | HEAD |
| `m0/alignment_note.md` | 2244 | `1bcee4f44f086d2ef6f5fc94a4d277432b58d52c741bc101c9bebb129a1714fa` | `34b182ce9b` | HEAD |
| `m0/prompts/V1.txt` | 1404 | `15fda37fd55b9a8235c6eb0a8172c67914d14b91f9eb1c3c4b0537bb1c1b99e6` | `184eeb49c5` | HEAD |
| `m0/prompts/V2.txt` | 1327 | `0b40cb62ebf7fb8c7c9befed65041cbe2e37b9abfd99b2e20f8fb6d94bd9c3cf` | `aa08837674` | HEAD |
| `m0/prompts/V3.txt` | 2053 | `0e1ae602302b14c706055cba813b9cd0e38cd817dc64059b451315f5d9115bd4` | `f595eca98d` | HEAD |
| `m0/results.csv` | 150 | `32eba1a22a6fb5d356c5b0b504dcab7aaf8165a8f131f53e0457f3c1f3a8dcaa` | `ed95f1a604` | HEAD |
| `m1/audit/P0-01-SAMPLE-CH01-report.md` | 32057 | `51ea0088ff6e886c1fd0b0e982cf829f9a543e0cd983ec38d354b6259101f5dd` | `51ea0088ff` | HEAD |
| `m1/audit/chapter-map.md` | 14142 | `9a7ab3b9e622b63fa8efd4e455cadc41bdaf8a9299f01a12d058b09f3b8f5d5f` | `9a7ab3b9e6` | HEAD |
| `m1/audit/script-audit-ch01.md` | 50383 | `59b744def661a674e8184ab4a7b16db37a11febff7af13de4144655a7e481bb4` | `59b744def6` | HEAD |
| `m1/capability_report.md` | 1482 | `6e117745d74cda9fc9af4b038871e824c9f278ab759e47510e33beda74d7036d` | `79459fc142` | HEAD |
| `m1/ch1/work/script.json` | 9471 | `1ac90fae164b1dbe9c1d77995f5b216bd7ca6f2eee9c9781f7e46dbd300a27f3` | `b3e10894a3` | HEAD |
| `m1/ch1/work/timeline.json` | 29690 | `bb76576f1595920193df6593d495a2964b31dc7b4e66ec839ad77db8d87703fa` | `254e8078aa` | HEAD |
| `m1/delivery.md` | 3388 | `f73b759c39e5d690b2b1658bf59bf4f3dca3d62abc8dc466d03598268fd81cb7` | `861cb9d9dd` | HEAD |
| `m1/labels/v1.json` | 1272 | `2ac310a6e9c788fef5b65287e12afa6f46d2cd090c1a1564711256e6e540c1fc` | `39ab1b6f39` | HEAD |
| `m1/labels/v2.json` | 1759 | `541e776671cd994c368cd94757e993b9f266fce1653520cad6ddbed2435a9f2d` | `a8bff9d9fb` | HEAD |
| `m1/v1/ch01/work/chapter.json` | 1216 | `5397af17356f2f88e9ec0caab5bead127b7ae110ef12eeb74953db7949e9b686` | `b2303175de` | HEAD |
| `m1/v1/ch01/work/novel_ref.json` | 24418 | `5d709aa051cb748e80d4ea89a7d733fd0fdfe8c7edc9593ea7b902067d75ad07` | `5d709aa051` | HEAD |
| `m1/v1/ch01/work/script-audit.json` | 40837 | `df1d4faa26700f86c088136f283cfdccce9cc0005ec54ff0488d7a000dde1f3b` | `df1d4faa26` | HEAD |
| `m1/v1/ch01/work/script.json` | 9471 | `1ac90fae164b1dbe9c1d77995f5b216bd7ca6f2eee9c9781f7e46dbd300a27f3` | `b3e10894a3` | HEAD |
| `m1/v1/ch01/work/timeline.json` | 29690 | `bb76576f1595920193df6593d495a2964b31dc7b4e66ec839ad77db8d87703fa` | `254e8078aa` | HEAD |
| `m1/v1/ch02/work/chapter.json` | 1051 | `1d068a0f74e1fd8da72cd2a3f8952ae116321324d159dc35a2d338c9f663755e` | `4bc119c7e9` | HEAD |
| `m1/v1/ch02/work/script.json` | 10789 | `8f2ab65093fb8cdab56f09b77b5aa8a2cf5fb08be5dcc2204224625f975cc77c` | `b3d390182c` | HEAD |
| `m1/v1/ch02/work/timeline.json` | 32564 | `6e0136a84b416c3d902bd4fad239647d061bd5db68478e13b7b3225581c520f3` | `1c3c82fd48` | HEAD |
| `m1/v1/ch03/work/chapter.json` | 1000 | `5dc7851cd7267548973c1d44907ce3225cf030011015e4e8ee6101d659fe3ad7` | `457f2da7ba` | HEAD |
| `m1/v1/ch03/work/script.json` | 6695 | `af0d8e2ee789f1585b7a5c12941bcd7bbc895b31b06592e1e98988ce11185a5f` | `9f17b86d86` | HEAD |
| `m1/v1/ch03/work/timeline.json` | 21616 | `98e22819b0d1ef2b30be2b518e3b69180bfd3cdd0f68f001e696fe5f41d07ab2` | `c6aa458e49` | HEAD |
| `m1/v1/ch04/work/chapter.json` | 1035 | `5beb93b6cb6f5909317c5017a999e2c41cdeb14a3fd0109086589f5fe3e530b4` | `8dd02ea694` | HEAD |
| `m1/v1/ch04/work/script.json` | 7257 | `4e4278a45bc2717905c10b48425f5faabb06ee0371efbe2e87f435fc1d9a1600` | `11ff7004e5` | HEAD |
| `m1/v1/ch04/work/timeline.json` | 21946 | `46da3168b5d8b9b67e3267d05b18899632d4bef311e7de5a028b91a44aea903a` | `b817d2934d` | HEAD |
| `m1/v1/ch05/work/chapter.json` | 854 | `307780bf330f532287c0d53d8e08b6ee8b93180e1c203379e22c9e5da962c8d3` | `76a70de12a` | HEAD |
| `m1/v1/ch05/work/script.json` | 5651 | `29bcace59f4a7853e85529ae8eecebabb99a090a3c687c5cfd100a775aa83333` | `4c30118385` | HEAD |
| `m1/v1/ch05/work/timeline.json` | 18975 | `21ad229cea341e40a9bf95434fd852e32d0615a3fb1d47b0fed74bed9f664a9e` | `abf35538b8` | HEAD |
| `m1/v1/work/chapter_index.json` | 2861 | `6b3319adc99b6f456d64bb2c0ce8dbafdf06d78c4d83edb3b5355908359a278c` | `f1ac1e1b9c` | HEAD |
| `m1/v2/ch06/work/chapter.json` | 1022 | `80cec9d02c5ce1f51a4059d667e5c424c075b290a6d90bbf4517608131aa8428` | `0af66c5ae0` | HEAD |
| `m1/v2/ch06/work/script.json` | 6418 | `88de7e4defb959b35561e540945655f06b7f168feada9c4b5d128585e03256c5` | `bfb453f170` | HEAD |
| `m1/v2/ch06/work/timeline.json` | 19523 | `b89b0cdafa76425e0d1a4a2b399faa588014607598db772edeb7b7b0bc9f00cd` | `a709d9baec` | HEAD |
| `m1/v2/ch07/work/chapter.json` | 652 | `2600a051ee3beb9cd49c67cfbfa3cbf979d6fce287bba791a725e8c1d833597b` | `42656be299` | HEAD |
| `m1/v2/ch07/work/script.json` | 2080 | `ac1e515062cd35dff4a494244ae602a071a4d1d93cb6792f913d237224976a0b` | `a72f589898` | HEAD |
| `m1/v2/ch07/work/timeline.json` | 7121 | `0461a4a666a6858d29d69659cd7d953410c27cc822d485324821238b049d2e70` | `f9d92ba7f5` | HEAD |
| `m1/v2/ch08/work/chapter.json` | 1023 | `4bd1c3421950a3dba374b3aced56e947bd9b6b521162ecced8f956c14547559f` | `fef41b1ef1` | HEAD |
| `m1/v2/ch08/work/script.json` | 6303 | `b72485e5a6104b4f1d33c592ec9beffbe9add50f1ce6b98241b9e43ba1409641` | `c35463e17e` | HEAD |
| `m1/v2/ch08/work/timeline.json` | 18290 | `3437ae20f83e4749855fa1d873ef7bc6db6b6133fc3a0bde05d5ef119904c8c3` | `9a47c58090` | HEAD |
| `m1/v2/ch09/work/chapter.json` | 813 | `fd2c940f12714e1b4a368e8ef1935a5ae04041d5a67ba7703f5274e7c730f67e` | `d9efbd4f86` | HEAD |
| `m1/v2/ch09/work/script.json` | 3358 | `2a5132ac32f1139024700e7c35c77028889eda8da8560fe5d88aebf1928ba21d` | `325670bc3a` | HEAD |
| `m1/v2/ch09/work/timeline.json` | 9791 | `7d2950b4e2e30a0046293111cf4194f51766c2d536ed82bdbb28e4883b103e5e` | `ddf071a793` | HEAD |
| `m1/v2/ch10/work/chapter.json` | 945 | `9fae2100492d62b09eb683a918d5b04570322f40afef97f736212f1d737c8ec7` | `e497b07c60` | HEAD |
| `m1/v2/ch10/work/script.json` | 4837 | `b8fa6de159d14e237f6ae339e72ee631755a26d89a799ccd825292a3919dbbb2` | `80efd6de91` | HEAD |
| `m1/v2/ch10/work/timeline.json` | 14655 | `96ee257f517eec5f4ea5fbb817492a086f7b30702eafb2a4cf1fd76300c4f6e4` | `be5c3a07ae` | HEAD |
| `m1/v2/work/chapter_index.json` | 3794 | `fe39fef2b419379b80f521fe73c83fb9aaf811feff3cc794caa0ff68cbfe2390` | `e4874ebbee` | HEAD |
| `m1/work/panels/page_0005.candidates.json` | 2059 | `3ccbd3b869e6a44a2678bf5c5377698b6368b16d8e04f7c88bfeecf52abe648b` | `93f22994b9` | HEAD |
| `m1/work/panels/page_0005.panels.json` | 286 | `2645393915d1d992ab015642733a2597935f2607432d9b8c728f62744e3b7651` | `b9842e3026` | HEAD |
| `m1/work/panels/page_0006.candidates.json` | 818 | `e14cf598dcb094572c86a9932da5c025f011317acf31e6f22b8d1e84dc01666a` | `086f7dbc58` | HEAD |
| `m1/work/panels/page_0006.panels.json` | 763 | `aad4894f594b4e544a11f5a07abf3beb6c95c05b315fb905cc5a77375a987e0c` | `08e0e16d81` | HEAD |
| `m1/work/panels/page_0007.candidates.json` | 777 | `8f395e3abf82204b0b8a4ef34b8c651a2ebab72c5c966c51d83f33795cfd7b86` | `2edf94803b` | HEAD |
| `m1/work/panels/page_0007.panels.json` | 443 | `9bfba34129b4536e2c62efc1d7d034615910e96ab7794a44ace550edc26f71d6` | `633a3031e7` | HEAD |
| `m1/work/panels/page_0008.candidates.json` | 461 | `827c70d0112d354da56c25cb9e41fc23af02fff92c5f3968f58f49b85bf248ed` | `80c199b5e5` | HEAD |
| `m1/work/panels/page_0008.panels.json` | 759 | `fd9b30809486df27e5a937adaf9af06104df599fbb3895692904f9a8933530c0` | `4147629fd5` | HEAD |
| `m1/work/panels/page_0009.candidates.json` | 502 | `787a379486e83ec4f83f74774ec16db33a01d886f52991e363ce2c8b374befa3` | `9c55c4151c` | HEAD |
| `m1/work/panels/page_0009.panels.json` | 601 | `598d819e5cc55396c5362448d38e91bf842ed30036e40852ebd8c035ae7914ee` | `732d1b0007` | HEAD |
| `m1/work/panels/page_0010.candidates.json` | 304 | `b93217bca1acf643e6af0e2cdc27b3685c0c5f8a30ce8f3f95b7aebd3992da0e` | `4579c9c0d0` | HEAD |
| `m1/work/panels/page_0010.panels.json` | 763 | `5ee2e2cb3d50e825d81f2f7b5d4e5641b99961eec54404e2a9e965c5de235c8f` | `2584b019e9` | HEAD |
| `m1/work/panels/page_0011.candidates.json` | 618 | `b482777ec3134a426aec7d58bc7b4edaf35866baaa9a067b8ccd84c8ef167fa2` | `96c2a88ef7` | HEAD |
| `m1/work/panels/page_0011.panels.json` | 763 | `ea31de28f5284e98c89c71bb41a8efe8aa578eb22d19ef6e92eec790452826fe` | `38d7ce2347` | HEAD |
| `m1/work/panels/page_0012.candidates.json` | 777 | `8ac6ccc25dad5b4e50759c3ff8598acc6ff9cd43cf4a7eccf47a737c8e1de6f0` | `a7da729211` | HEAD |
| `m1/work/panels/page_0012.panels.json` | 601 | `b314775476257c47b561f15a8b96a0e45b4b11ecd7e0db3438c9d9f9a116fc63` | `615a48b0d9` | HEAD |
| `m1/work/script.json` | 2166 | `ac9c3338128fab2121a57115d5614b5bcbe59b70c1b07e274b4f5ca46b58e5c8` | `aef7b2eade` | HEAD |
| `m1/work/timeline.json` | 6349 | `9daae796d5fb8e1c05d864ecca31ee7b4ba497667fc8859cdd1057f4df3207db` | `2f786dffd6` | HEAD |
| `panelcast/__init__.py` | 86 | `5507001c8992326e6693ae8f724d0b2a42868a99104b2e4b54a343ac28ff6704` | `7f917a9f5c` | HEAD |
| `panelcast/__main__.py` | 26671 | `558ff9d8b71bd1bde1f740fe16237344fe72862ea46364fb6ab156ba1a6c92b8` | `f4b5519850` | HEAD |
| `panelcast/chapters.py` | 14971 | `3249fd72989a87cf795b2edfd5d3bb31d7a93e5ab3085836ca871c91784ea444` | `78545dde51` | HEAD |
| `panelcast/editor/server.py` | 16252 | `17402694bd39059c07545f72c2b7ca17a5a48571fb62a258a9fc561b244f4027` | `0a28f65a9d` | HEAD |
| `panelcast/editor/static/index.html` | 24230 | `ce76ca9bc44a7c976286484f065f6c5b973917c76b94a52c359e86acebeeb818` | `5649980a0e` | HEAD |
| `panelcast/epub_ingest.py` | 4364 | `88df0fd69ddfa0543a0ec8647f10500894167ad1bc5a9cf2bfd0d8a3bad54d47` | `45e37261cc` | HEAD |
| `panelcast/errors.py` | 115 | `afab242f8b9ac2e6e3e2ccc6aacb27fa31031d3dc2b2ddd7e20ac7e9dc117171` | `b9e7c16f65` | HEAD |
| `panelcast/identity.py` | 28955 | `eafedcf485038b7812a3cd2f81f7a8764cac124f46286a8b130336277656dc2b` | `79fd7ca168` | HEAD |
| `panelcast/jpeg.py` | 1784 | `b0e2ce02ab9080b6fb21edf66fef08c194b0d09961eafc19e8fc61a342990c76` | `610b31bcbb` | HEAD |
| `panelcast/manifest.py` | 4628 | `abfeec0bb8b88d386d8e0b7f5e834a36bbccc260af1c33a8751209fdee1eff18` | `c951d2dc20` | HEAD |
| `panelcast/mobi_ingest.py` | 2764 | `5eb15c6bcacbffa1a6ba1c667b8a65e21979826c39fbdf8bfc3f7c3fa59a04a0` | `77c477fd63` | HEAD |
| `panelcast/novel.py` | 41585 | `d464ca05e4c6ff9f0041898677d8b53672296e48f7a274538019968d24028c37` | `baf615af92` | HEAD |
| `panelcast/panels.py` | 14815 | `f4752ceb12587b95961bb80945e8bca68a18af8f4f17f9c0f452c2d2e0d03b47` | `2ad48721bc` | HEAD |
| `panelcast/profile.py` | 11137 | `ec9627d77d091c1e1c37810c2754b1c57a4146648cca851ec58a2c19871e3ea9` | `231b0c78f6` | HEAD |
| `panelcast/profile_auto.py` | 9689 | `0ba66aef171d01075e1b136898dc81a10dda20ab24193a33451759fe0314b1ab` | `aca4d7a01f` | HEAD |
| `panelcast/render.py` | 13781 | `c0aea9d93407f8b5e3fa5f8df7c55dad9aab466671173652da4deb41c81eb3fe` | `3184a980c7` | HEAD |
| `panelcast/timeline.py` | 19586 | `e328372bd93fb971833c74972be584169a7f317503a4c5ceed031baffdd1df69` | `c902bca17b` | HEAD |
| `panelcast/tts.py` | 11860 | `c6290430b5a39e74bf31123e0ea9ceb1c71aa21f54aed2fa4141ff0b37abe97d` | `cde84de39a` | HEAD |
| `panelcast/verify.py` | 15347 | `4db5ee7d164d85df6dfc745a0a566e9165771a34c322e649669320ada6f30027` | `78f0c7a172` | HEAD |
| `pyproject.toml` | 395 | `08bc4fe1e5e4eeb8d444eb5c0105273b9bcca257a95284ed085c35979c26ceae` | `a87a12a4f3` | HEAD |
| `tests/test_chapters.py` | 12386 | `8bd941599ce5b38d4bd35bcbcf2b59978effc8815111a7a9be8ed62ba17ef19c` | `53e35e85d0` | HEAD |
| `tests/test_cli.py` | 15655 | `80381b7858ae2a0f8737830ab269499ba9b5fb02c349438ba6de7b8cb34706dd` | `05150e9bb0` | HEAD |
| `tests/test_editor.py` | 8926 | `525c10e23bf1254eecd8f2ee42701b3a39e6d95227cbf8496e7f92a6877badac` | `f2cd9f3149` | HEAD |
| `tests/test_epub.py` | 4564 | `86af2c6450b97bdd455cf26bcc28f37777963624b4bf868f44c109545dcf20a3` | `7b661eb061` | HEAD |
| `tests/test_identity.py` | 41401 | `6320c18abff8bf484eb141134b7051b0d0811d1cc5f9f828e84cbfd8a81ccf5b` | `60b3d3db0d` | HEAD |
| `tests/test_lf.py` | 9294 | `76ef5f4652ea0db6dee21c1dcdc68114cf5c54290f061c57821a3be85a3c6bb3` | `0227afef31` | HEAD |
| `tests/test_manifest.py` | 5434 | `4f27b5a5f09c2410808642630848c08ddad2a073cb15907981cd7fcf07a70eb4` | `2696ad3085` | HEAD |
| `tests/test_mobi.py` | 4079 | `a88db279f0887df762c8280ad00d14f858ef0b4d087ea567716401b0c64bab84` | `8db17357ba` | HEAD |
| `tests/test_novel.py` | 58654 | `22c6cdbbcf3275e38b062a9721cbd1bb09cd603417fde637af83872e5e688252` | `e305639f90` | HEAD |
| `tests/test_novel_extract.py` | 6831 | `0ea6f375505e2bf22b30a10cdc0e44eebbd1211aa5d1b7d0351069771d3da325` | `fbe2427294` | HEAD |
| `tests/test_page_windows.py` | 7459 | `8c7adf405067245a9bc9977ee7fcef76896be495b507ddfacc8025e95b95f69f` | `5f86ce2f37` | HEAD |
| `tests/test_panels.py` | 4284 | `c564420a395285a6726363246d6ccd8a8ac82d9fd8d72b76a72decf236431b7f` | `6c698eec26` | HEAD |
| `tests/test_profile.py` | 11571 | `7e3d79b9d8f13bd838b1bfa0e6e58c6b453f19088c252a37ab53523f8ce04c05` | `3c2f45ba0b` | HEAD |
| `tests/test_profile_auto.py` | 5450 | `af0c9f84ea828c47523fcabe2fb794279b6755b6132e21b92fea06845cfd1c27` | `293989af34` | HEAD |
| `tests/test_render.py` | 6937 | `ca3fa6bb3329a91c040d8866ad62438b6a22b188666ad1216e36bf65cf841967` | `4afd87edee` | HEAD |
| `tests/test_timeline.py` | 10314 | `c880c602321931cd0629ee6abf56cc681ad320adce2ba858d875d7a8e8311bca` | `166d2999f6` | HEAD |
| `tests/test_tts.py` | 9142 | `1f182d8dffd12ecd249ec9574fd588352312ad0785b46c8e0b57ad420561e6c0` | `7b24a86054` | HEAD |
| `tests/test_verify.py` | 9228 | `cd28ac075ea6c65dae154c55c39115a5b6c1b2bfae8d4df667da3af03374f492` | `a1f103200f` | HEAD |
| `tools/contact_sheet.py` | 3569 | `558a39bf574ea671839cf61005e12e85f9e67086007cc741da5393233a34afea` | `41551e4c47` | HEAD |
| `tools/novel_extract.py` | 5515 | `c99df2bc7e024d884e5203e0e8c247c8bac716723a2c66662e8a83983078a697` | `4ca8a49ef1` | HEAD |
| `tools/strip_sheet.py` | 3310 | `008f83b24aeb42e257c6f7ab8e4f06157c3951f1cad6699f794fd689052f2d4d` | `b18b83861c` | HEAD |

## 未纳入本仓库的内容及原因

| 类别 | 例子 | 原因 |
| --- | --- | --- |
| 漫画原始素材 | `この素晴らしい世界に祝福を！/漫画/*.mobi`（约 1.5 GB） | 版权原文，`.gitignore` 已排除 |
| 小说 EPUB | `*.epub` | 同上 |
| 漫画页图 | `*.jpg` / `*.png`（2,000+ 张） | 从 MOBI 派生的中间产物，可重新摄取 |
| 配音与合成音频 | `*.wav`（459 个） | 中间产物，可由 `tts.py` 重生成 |
| 成片 | `*.mp4`（12 个） | 渲染产物，可由流水线重生成 |
| 渲染缓存 | `*/cache/`、`*/audio/`、`*/pages/` | 中间产物，无审计价值 |
| 本地工作区 | `.local/`、`.workbuddy-ai/` | 个人配置与 Agent 痕迹，非项目交付物 |

被追踪的 122 个文件（不含本清单）全部纳入；
以上类别由 `.gitignore` 排除，不属于「代码内容」。

## 复核方式

```bash
git clone https://github.com/iop666/PanelCast-Code.git
cd PanelCast-Code
python -m unittest discover -s tests      # Ran 430 tests / OK (skipped=2)
git ls-files --eol | grep -c "i/crlf"    # 0

# 逐文件核对：取本清单表格，对每个文件重算 sha256 与 blob sha，
# 并与 GitHub Git Tree API 的 sha 比对。
```

## 签核边界

第一章 `m1/v1/ch01/work/script-audit.json` 保持
`review_status: pending_human`、`reviewed_by: null`。
P0-08 完成不等于第一章自动获得签核；机器不能替人签核。
第二章、九章批量、P0-06、P0-10、横版开发继续冻结。
