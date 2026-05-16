<!-- Pull Request 模板：幫助維持 CI 與 Codecov 檢查的一致性 -->

## 變更說明

- 簡短描述這次 PR 的目的與主要改動。

## 檢查清單 (合併前請完成)

- [ ] CI 執行成功（所有 job green）。
- [ ] 單元測試通過（`pytest` 本地或 CI）。
- [ ] 重要修改已加對應單元測試或整合測試。若無，請在 PR 說明中註明理由。
- [ ] Lint/格式檢查已通過（`black`/`isort`/`flake8`/`pylint`）。
- [ ] 若涉及 Models/Telegram 關鍵設定，已確認不會在 logs 中輸出 secrets。

## 合併後檢查（維護者檢查）

- [ ] 確認分支 CI 成功並產生 `coverage.xml`（artifact: `coverage-xml`）。
- [ ] 檢視 Codecov 報表（badge / project page），確認 coverage 正常顯示。
- [ ] 若為私有倉庫且上傳失敗：請在 Settings → Secrets 新增 `CODECOV_TOKEN`，然後重新執行 workflow。

## 其他說明

- 若 PR 涉及運行參數（例如 backoff、retry 設定），建議在 README 或 `.env.example` 同步更新說明。
