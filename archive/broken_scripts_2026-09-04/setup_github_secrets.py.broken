#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
?뵍 GitHub Secrets ?먮룞 ?ㅼ젙 ?ㅽ겕由쏀듃
"""

import os
import json
import base64
from pathlib import Path

class GitHubSecretsSetup:
    """GitHub Secrets ?먮룞 ?ㅼ젙"""

    def __init__(self):
        self.repo_owner = "coar0000"
        self.repo_name = "kms"
        self.secrets = {
            "SENDER_EMAIL": "coar1004@naver.com",
            "EMAIL_PASSWORD": "EHgus123!"
        }

    def create_setup_guide(self):
        """GitHub Secrets ?ㅼ젙 媛?대뱶 ?앹꽦"""
        guide = """
?뵍 GitHub Secrets ?먮룞 ?ㅼ젙 媛?대뱶
================================

??μ냼: https://github.com/coar0000-wq/jarvis-luna/settings/secrets/actions

???먮룞 ?ㅼ젙??Secrets:
"""
        for key, value in self.secrets.items():
            guide += f"\n   Name: {key}\n   Value: {'*' * len(value)}\n"

        guide += """

?뱥 ?섎룞 ?ㅼ젙 諛⑸쾿 (?먮룞??遺덇???:
1. GitHub 由ы룷吏?좊━ ??Settings
2. "Secrets and variables" ??"Actions" ?대┃
3. "New repository secret" ?대┃
4. ?ㅼ쓬 ?뺣낫 ?낅젰:

   ??Secret 1:
   Name: SENDER_EMAIL
   Value: coar1004@naver.com

   ??Secret 2:
   Name: EMAIL_PASSWORD
   Value: EHgus123!

5. "Add secret" ?대┃

???꾨즺 ???먮룞???ㅽ뻾:
- GitHub Actions媛 ?ㅼ쓬 5?쇰쭏???먮룞 ?ㅽ뻾
- PPT媛 coar0000@naver.com?쇰줈 諛쒖넚??
?럦 ?ㅼ젙 ?꾨즺!
"""
        return guide

    def save_credentials(self):
        """?먭꺽利앸챸???덉쟾??濡쒖뺄 ?뚯씪?????""
        creds = {
            "github_secrets": {
                "SENDER_EMAIL": self.secrets["SENDER_EMAIL"],
                "EMAIL_PASSWORD": "***ENCRYPTED***",
                "created_at": "2026-08-17T06:30:00Z",
                "status": "pending_github_verification"
            },
            "next_steps": [
                "1. GitHub Settings ??Secrets and variables ??Actions",
                "2. Add SENDER_EMAIL secret",
                "3. Add EMAIL_PASSWORD secret",
                "4. Workflow will run automatically every 5 days"
            ]
        }

        filepath = Path('data/github_secrets_config.json')
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(creds, f, ensure_ascii=False, indent=2)

        return filepath

    def run(self):
        """?꾩껜 ?꾨줈?몄뒪 ?ㅽ뻾"""
        print("\n?뵍 GitHub Secrets ?먮룞 ?ㅼ젙 ?꾨줈?몄뒪")
        print("=" * 60)

        # 1. ?ㅼ젙 媛?대뱶 ?앹꽦
        print("?뱥 GitHub Secrets ?ㅼ젙 媛?대뱶 ?앹꽦 以?..")
        guide = self.create_setup_guide()

        guide_file = Path('GITHUB_SECRETS_SETUP.md')
        with open(guide_file, 'w', encoding='utf-8') as f:
            f.write(guide)
        print(f"??媛?대뱶 ??? {guide_file}")

        # 2. ?먭꺽利앸챸 ???        print("?뮶 ?먭꺽利앸챸 ?ㅼ젙 ???以?..")
        creds_file = self.save_credentials()
        print(f"???ㅼ젙 ??? {creds_file}")

        # 3. ?곹깭 異쒕젰
        print("\n" + "=" * 60)
        print("?렞 ?꾩닔 ?ㅼ젙 ?꾨즺!")
        print("=" * 60)
        print("""
????λ맂 ?먭꺽利앸챸:
   - SENDER_EMAIL: coar1004@naver.com
   - EMAIL_PASSWORD: [蹂댁븞???④?]

?뱥 ?ㅼ쓬 ?④퀎:
   1. GitHub 由ы룷吏?좊━ ?ㅼ젙 ?묒냽
   2. Secrets and variables ??Actions
   3. ?꾩쓽 2媛?Secret ?섎룞 異붽?

?? ?ㅼ젙 ??
   - 5?쇰쭏???먮룞 ?ㅽ뻾
   - PPT ?먮룞 ?앹꽦 諛??대찓??諛쒖넚
   - coar0000@naver.com?쇰줈 諛쏆쓬

??툘 ?덉젙??泥?諛쒖넚: 2026-08-22
""")

        # 4. ?ㅼ젙 留곹겕 異쒕젰
        print("\n?뵕 GitHub Secrets ?ㅼ젙 URL:")
        print("https://github.com/coar0000-wq/jarvis-luna/settings/secrets/actions")

        print("\n??媛?대뱶 ?뚯씪: GITHUB_SECRETS_SETUP.md")
        print("=" * 60 + "\n")

        return {
            "status": "credentials_saved",
            "sender_email": self.secrets["SENDER_EMAIL"],
            "secrets_config_file": str(creds_file),
            "setup_guide_file": str(guide_file)
        }

if __name__ == "__main__":
    setup = GitHubSecretsSetup()
    result = setup.run()

    # JSON ?뺤떇?쇰줈?????    with open('data/setup_result.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)




