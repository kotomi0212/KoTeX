# TeX構文・書式チェッカー

プロジェクト直下で次を実行する．

```powershell
.\check.ps1
```

用語，句読点・括弧・数値・図表キャプション，IEEE形式の参考文献，ビルド済みPDF上の図表配置を順に検査する．PDF配置検査には `main.pdf` と `main.aux` が必要なため，先に `.\build.ps1` を実行する．

構文・書式だけを検査し，PDF配置検査を省略する場合：

```powershell
.\check.ps1 -SkipLayout
```

チェッカー自身のテストも実行する場合：

```powershell
.\check.ps1 -RunTests
```

VS Codeでは「ターミナル」→「タスクの実行」→「Check TeX format」から実行できる．

終了コードは合格が `0`，規則違反が `1`，入力不整合や実行不能が `2` である．`WARNING` と `INFO` は確認事項であり，それだけでは不合格にならない．

用語規則は `writing_rules/forbidden_terms.json` に追加する．各規則は検出用の正規表現，重大度，推奨表記を持つ．コメント，数式，引用キー，ラベル，URLなどは用語検査から除外される．
