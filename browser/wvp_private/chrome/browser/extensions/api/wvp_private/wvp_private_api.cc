// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/extensions/api/wvp_private/wvp_private_api.h"

#include <utility>

#include "base/functional/bind.h"
#include "base/strings/strcat.h"
#include "base/strings/utf_string_conversions.h"
#include "base/values.h"
#include "chrome/browser/extensions/extension_tab_util.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/common/extensions/api/wvp_private.h"
#include "components/autofill/content/browser/content_autofill_client.h"
#include "components/autofill/core/common/autofill_prefs.h"
#include "components/prefs/pref_service.h"
#include "components/prefs/scoped_user_pref_update.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"
#include "net/base/schemeful_site.h"
#include "ui/gfx/geometry/rect_f.h"
#include "url/origin.h"

namespace extensions {

namespace approve = api::wvp_private::Approve;

WvpPrivateApproveFunction::WvpPrivateApproveFunction() = default;
WvpPrivateApproveFunction::~WvpPrivateApproveFunction() = default;

ExtensionFunction::ResponseValue WvpPrivateApproveFunction::Reply(
    bool allowed,
    const std::string& reason) {
  api::wvp_private::Answer answer;
  answer.allowed = allowed;
  answer.reason = reason;
  answer.origin = origin_;
  return ArgumentList(approve::Results::Create(answer));
}

ExtensionFunction::ResponseAction WvpPrivateApproveFunction::Run() {
  std::optional<approve::Params> params = approve::Params::Create(args());
  EXTENSION_FUNCTION_VALIDATE(params);
  const api::wvp_private::Request& request = params->request;

  content::WebContents* contents = nullptr;
  if (!ExtensionTabUtil::GetTabById(request.tab_id, browser_context(),
                                    /*include_incognito=*/true, &contents) ||
      !contents) {
    return RespondNow(Error("no such tab"));
  }
  // Always the top frame, and the origin is the browser's own record of it.
  content::RenderFrameHost* rfh = contents->GetPrimaryMainFrame();
  const url::Origin origin = rfh->GetLastCommittedOrigin();
  if (origin.opaque()) {
    return RespondNow(Reply(false, "bad_origin"));
  }
  origin_ = origin.Serialize();

  // One gesture, one use. Script alone can't produce this bit.
  if (request.require_activation && !rfh->ConsumeTransientUserActivation()) {
    return RespondNow(Reply(false, "no_activation"));
  }
  if (!request.ask_user) {
    return RespondNow(Reply(true, "ok"));
  }

  // One prompt per origin and mode. The prompt is browser UI, so a page can't
  // cover it or click it for the user.
  const std::string pref_key =
      base::StrCat({"wvp|", origin_, "|", request.mode});
  PrefService* prefs = Profile::FromBrowserContext(browser_context())->GetPrefs();
  if (prefs->GetDict(autofill::prefs::kAutofillEmailVerificationState)
          .FindBool(pref_key)
          .value_or(false)) {
    return RespondNow(Reply(true, "ok"));
  }

  auto* client = autofill::ContentAutofillClient::FromWebContents(contents);
  if (!client) {
    return RespondNow(Error("no autofill client"));
  }
  // The "wvp:" prefix tells the popup view to use WVP text.
  client->ShowEmailVerificationPopup(
      gfx::RectF(request.x, request.y, request.width, request.height),
      net::SchemefulSite(origin),
      base::UTF8ToUTF16(base::StrCat({"wvp:", origin_, " gets a proof of: ",
                                      request.text})),
      base::BindOnce(&WvpPrivateApproveFunction::OnDecision, this,
                     request.tab_id, pref_key));
  return RespondLater();
}

void WvpPrivateApproveFunction::OnDecision(int tab_id,
                                           const std::string& pref_key,
                                           UiStatus status) {
  if (!browser_context()) {
    return;
  }
  const bool allowed = status == UiStatus::kAllowed;
  if (allowed) {
    ScopedDictPrefUpdate(Profile::FromBrowserContext(browser_context())->GetPrefs(),
                         autofill::prefs::kAutofillEmailVerificationState)
        ->Set(pref_key, true);
    // The EVP popup keeps a spinner until told to close. Close it now.
    content::WebContents* contents = nullptr;
    if (ExtensionTabUtil::GetTabById(tab_id, browser_context(),
                                     /*include_incognito=*/true, &contents) &&
        contents) {
      if (auto* client =
              autofill::ContentAutofillClient::FromWebContents(contents)) {
        client->HideEmailVerificationPopup();
      }
    }
  }
  Respond(Reply(allowed, allowed ? "ok" : "declined"));
}

}  // namespace extensions
