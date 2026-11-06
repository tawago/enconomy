// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_EXTENSIONS_API_WVP_PRIVATE_WVP_PRIVATE_API_H_
#define CHROME_BROWSER_EXTENSIONS_API_WVP_PRIVATE_WVP_PRIVATE_API_H_

#include <string>

#include "components/autofill/core/browser/foundations/autofill_client.h"
#include "extensions/browser/extension_function.h"

namespace extensions {

class WvpPrivateApproveFunction : public ExtensionFunction {
 public:
  DECLARE_EXTENSION_FUNCTION("wvpPrivate.approve", UNKNOWN)
  WvpPrivateApproveFunction();

  WvpPrivateApproveFunction(const WvpPrivateApproveFunction&) = delete;
  WvpPrivateApproveFunction& operator=(const WvpPrivateApproveFunction&) =
      delete;

 protected:
  ~WvpPrivateApproveFunction() override;
  ResponseAction Run() override;

 private:
  using UiStatus = autofill::AutofillClient::EmailVerificationPermissionUiStatus;
  ResponseValue Reply(bool allowed, const std::string& reason);
  void OnDecision(int tab_id, const std::string& pref_key, UiStatus status);

  std::string origin_;
};

}  // namespace extensions

#endif  // CHROME_BROWSER_EXTENSIONS_API_WVP_PRIVATE_WVP_PRIVATE_API_H_
