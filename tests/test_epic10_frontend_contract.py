from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/"web"
def read(p): return (ROOT/p).read_text(encoding="utf-8")

def test_organization_navigation_and_surfaces_exist():
    shell=read("components/epic1/app-shell.tsx")
    assert '"Team & Access","/app/organization",true' in shell
    for rel in ["app/(dashboard)/app/organization/page.tsx","app/(dashboard)/app/organization/team/page.tsx","app/(dashboard)/app/organization/clients/page.tsx","app/(dashboard)/app/organization/access/page.tsx","app/(dashboard)/app/organization/activity/page.tsx"]: assert (ROOT/rel).exists()

def test_restricted_members_do_not_fetch_portfolios_in_global_context():
    ctx=read("lib/epic1/context.ts")
    assert 'account_access_mode' in ctx and 'Promise.resolve([])' in ctx

def test_invite_ui_warns_raw_capability_is_one_time():
    text=read("components/epic10/invite-form.tsx")
    assert "shown only now" in text
    assert "/accept-invite/" in text

def test_access_ui_separates_visibility_from_responsibility():
    text=read("app/(dashboard)/app/organization/access/page.tsx")
    assert "an assignment never grants access by itself" in text

def test_admin_ui_does_not_offer_owner_mutation_controls():
    invite=read("components/epic10/invite-form.tsx")
    team=read("app/(dashboard)/app/organization/team/page.tsx")
    assert 'actorRole==="owner"&&<option value="owner">Owner</option>' in invite
    assert 'Owner access can only be changed by another Owner.' in team
    assert 'i.role!=="owner"||x.membership!.role==="owner"' in team
