## Description: <br>
CloudBase guides agents through developing, deploying, debugging, migrating, and troubleshooting Tencent CloudBase projects across Web, WeChat Mini Program, native app, database, serverless, CloudRun, storage, AI model, agent, and operations workflows. <br>

This skill is ready for commercial/non-commercial use. <br>

## Publisher: <br>
[binggg](https://clawhub.ai/user/binggg) <br>

### License/Terms of Use: <br>
MIT-0 <br>


## Use Case: <br>
Developers and engineers use this skill to route CloudBase tasks to the right reference material, generate implementation guidance, configure MCP-based management access, and produce code, commands, and deployment steps for CloudBase applications. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: The skill can guide high-impact CloudBase administration, including deployments, permission changes, public endpoints, payment or auth configuration, and credential use. <br>
Mitigation: Require explicit confirmation before those actions, verify region, auth method, and EnvId with the user, and review proposed changes before execution. <br>
Risk: The skill references MCP and package-based tooling that can affect cloud resources. <br>
Mitigation: Pin or vet the MCP package version where possible and inspect tool schemas before using CloudBase management tools. <br>
Risk: Unsafe examples such as no-auth or wildcard-CORS patterns can be copied into production if not reviewed. <br>
Mitigation: Avoid promoting no-auth or wildcard-CORS examples for production and require security review for public endpoints. <br>


## Reference(s): <br>
- [CloudBase ClawHub Release](https://clawhub.ai/binggg/cloudbase) <br>
- [CloudBase Main Entry](https://cnb.cool/tencent/cloud/cloudbase/cloudbase-skills/-/git/raw/main/skills/cloudbase/SKILL.md) <br>
- [CloudBase MCP Setup](references/mcp-setup.md) <br>
- [Web Development Reference](references/web-development/SKILL.md) <br>
- [Cloud Functions Reference](references/cloud-functions/SKILL.md) <br>
- [CloudBase Agent Reference](references/cloudbase-agent/SKILL.md) <br>
- [CloudBase Web SDK CDN](https://static.cloudbase.net/cloudbase-js-sdk/latest/cloudbase.full.js) <br>


## Skill Output: <br>
**Output Type(s):** [Text, Markdown, Code, Shell commands, Configuration, Guidance] <br>
**Output Format:** [Markdown with inline code blocks, shell commands, configuration snippets, and implementation guidance] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [May propose CloudBase management, deployment, auth, payment, public endpoint, and credential-handling actions that require user confirmation before execution.] <br>

## Skill Version(s): <br>
1.92.0 (source: ClawHub release metadata; artifact frontmatter reports 2.21.1) <br>

## Ethical Considerations: <br>
Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment. <br>
