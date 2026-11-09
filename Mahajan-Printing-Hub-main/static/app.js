document.addEventListener('DOMContentLoaded', () => {
  const MAX_FILES = 10;
  const MAX_TOTAL_FILE_BYTES = 200 * 1024 * 1024;
  const DUPLICATE_FILE_MESSAGE = 'একই নামে একাধিক ফাইল আপলোড করা যাবে না।';
  const FILE_LIMIT_MESSAGE = 'একসাথে ১০টার বেশি ফাইল ও ২০০ এমবির বেশি ফাইল আপলোড করা যাবে না।';
  let uploadedFiles = [];
  let calculatedOrder = null;

  const pdfInput = document.getElementById('pdfFile');
  const dropZone = document.getElementById('dropZone');
  const fileMetaList = document.getElementById('fileMetaList');
  const totalPageNum = document.getElementById('totalPageNum');
  const toStep2Btn = document.getElementById('toStep2');
  const fileLimitModal = document.getElementById('fileLimitModal');
  const fileLimitMessage = document.getElementById('fileLimitMessage');
  const orderForm = document.getElementById('orderForm');
  const orderError = document.getElementById('orderError');

  if (pdfInput) {
    pdfInput.addEventListener('change', (e) => {
      if (e.target.files && e.target.files.length > 0) {
        handleFiles(e.target.files);
        pdfInput.value = '';
      }
    });
  }

  // Drag & Drop
  if (dropZone) {
    dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('dragover');
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        handleFiles(e.dataTransfer.files);
      }
    });
  }

  function handleFiles(files) {
    const selectedFiles = Array.from(files).filter(candidate => candidate.type === 'application/pdf' || candidate.name.toLowerCase().endsWith('.pdf'));
    const nextFiles = [...uploadedFiles, ...selectedFiles];
    const combinedSize = nextFiles.reduce((total, file) => total + file.size, 0);
    const fileNames = nextFiles.map(file => file.name.split(/[\\/]/).pop().toLowerCase());
    const hasDuplicateNames = fileNames.length !== new Set(fileNames).size;
    const hasOverLimit = combinedSize > MAX_TOTAL_FILE_BYTES;
    const hasTooManyFiles = nextFiles.length > MAX_FILES;

    if (hasDuplicateNames) {
      showFileLimitModal(DUPLICATE_FILE_MESSAGE);
      return;
    }
    if (hasTooManyFiles || hasOverLimit) {
      showFileLimitModal(FILE_LIMIT_MESSAGE);
      return;
    }

    uploadedFiles = nextFiles;
    calculatedOrder = null;

    renderFileList();
    calculateTotalPagesAndBill();
    if (uploadedFiles.length > 0) {
      calculatePrice().catch(showCalculationError);
    }
  }

  function showFileLimitModal(message = FILE_LIMIT_MESSAGE) {
    if (fileLimitMessage) fileLimitMessage.innerText = message;
    if (fileLimitModal) {
      fileLimitModal.classList.remove('hidden');
      fileLimitModal.setAttribute('aria-hidden', 'false');
    }
  }

  function renderFileList() {
    if (!fileMetaList) return;
    fileMetaList.innerHTML = '';
    
    if (uploadedFiles.length === 0) {
      if (toStep2Btn) toStep2Btn.disabled = true;
      return;
    }
    
    if (toStep2Btn) toStep2Btn.disabled = false;

    uploadedFiles.forEach((file, index) => {
      const item = document.createElement('div');
      item.className = 'flex items-center justify-between rounded-xl bg-slate-50 p-3.5 border border-slate-200 text-sm mb-2';
      item.innerHTML = `
        <div class="flex items-center gap-3">
          <span class="grid h-8 w-8 place-items-center rounded-lg bg-blue-100 text-royalBlue font-bold text-xs">PDF</span>
          <div>
            <strong class="block text-navy font-bold">${file.name}</strong>
            <span class="text-xs text-slate-500">${file.page_count ?? '...'} pages · ${(file.size / (1024 * 1024)).toFixed(2)} MB</span>
          </div>
        </div>
        <button type="button" onclick="window.removeFile(${index})" class="text-slate-400 hover:text-red-500 p-1 font-bold text-lg">
          ✕
        </button>
      `;
      fileMetaList.appendChild(item);
    });

    if (window.lucide) lucide.createIcons();
  }

  window.removeFile = (index) => {
    uploadedFiles.splice(index, 1);
    calculatedOrder = null;
    renderFileList();
    calculateTotalPagesAndBill();
    if (uploadedFiles.length > 0) calculatePrice().catch(showCalculationError);
  };

  const closeFileLimitModal = () => {
    if (fileLimitModal) {
      fileLimitModal.classList.add('hidden');
      fileLimitModal.setAttribute('aria-hidden', 'true');
    }
  };
  document.getElementById('closeFileLimitModal')?.addEventListener('click', closeFileLimitModal);
  fileLimitModal?.addEventListener('click', (event) => {
    if (event.target === fileLimitModal) closeFileLimitModal();
  });

  function calculateTotalPagesAndBill() {
    if (uploadedFiles.length === 0) {
      if (totalPageNum) totalPageNum.innerText = '0';
      updateBill(0);
      return;
    }

    if (totalPageNum) totalPageNum.innerText = '...';
    updateBill(0);
  }

  function spiralBindingCost(pageCount) {
    if (pageCount <= 100) return 70;
    if (pageCount <= 200) return 100;
    return 180;
  }

  function currentBindingCost(pageCount, details) {
    return document.getElementById('binding').value === 'spiral'
      ? spiralBindingCost(pageCount)
      : Number(details.binding_cost);
  }

  function updateBill(pages, details = null) {
    const billPages = document.getElementById('billPages');
    const billPrint = document.getElementById('billPrint');
    const billBinding = document.getElementById('billBinding');
    const billDelivery = document.getElementById('billDelivery');
    const billTotal = document.getElementById('billTotal');

    if (pages === 0) {
      if (billPages) billPages.innerText = '0 pages';
      if (billPrint) billPrint.innerText = '৳ 0.00';
      if (billBinding) billBinding.innerText = '৳ 0.00';
      if (billDelivery) billDelivery.innerText = '৳ 0.00';
      if (billTotal) billTotal.innerText = '৳ 0.00';
      return;
    }

    if (billPages) billPages.innerText = `${pages} pages`;
    if (billPrint) billPrint.innerText = details ? `৳ ${Number(details.print_cost).toFixed(2)}` : 'Calculated after file upload';
    if (billBinding) billBinding.innerText = details ? `৳ ${currentBindingCost(pages, details).toFixed(2)}` : '৳ 0.00';
    if (billDelivery) billDelivery.innerText = details ? `৳ ${Number(details.delivery_cost).toFixed(2)}` : 'Calculated after file upload';
    if (billTotal) billTotal.innerText = details ? `৳ ${Number(details.grand_total).toFixed(2)}` : 'Calculated after file upload';
  }

  function selectedValue(name) {
    return document.querySelector(`input[name="${name}"]:checked`).value;
  }

  function syncGsmOptions() {
    const gsm = document.getElementById('gsm');
    const isLegal = selectedValue('paper_size') === 'Legal';
    const lightOption = gsm?.querySelector('option[value="65"]');
    if (!gsm || !lightOption) return;
    lightOption.disabled = isLegal;
    if (isLegal && gsm.value === '65') gsm.value = '70';
  }

  async function calculatePrice() {
    if (uploadedFiles.length === 0) return null;
    const formData = new FormData();
    uploadedFiles.forEach((file) => formData.append('files', file));
    formData.append('paper_size', selectedValue('paper_size'));
    formData.append('gsm', document.getElementById('gsm').value);
    formData.append('color_type', selectedValue('color_type'));
    formData.append('print_side', selectedValue('print_side'));
    formData.append('binding', document.getElementById('binding').value);
    formData.append('delivery_option', document.getElementById('deliveryOption').value);
    formData.append('copies', document.getElementById('copies').value);

    const response = await fetch('/api/calculate', { method: 'POST', body: formData });

    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Server error: ${response.status} ${response.statusText} - ${errorText}`);
    }

    const data = await response.json();
    if (data.status !== 'success') {
      const error = new Error(data.detail || 'Unable to calculate price.');
      if (error.message.includes('একই নামে')) {
        showFileLimitModal(DUPLICATE_FILE_MESSAGE);
      } else if (response.status === 413 || error.message.includes('একসাথে ১০টার বেশি')) {
        showFileLimitModal(FILE_LIMIT_MESSAGE);
      }
      throw error;
    }
    calculatedOrder = data;
    uploadedFiles.forEach((file, index) => {
      file.page_count = data.files[index]?.page_count ?? 0;
    });
    renderFileList();
    if (totalPageNum) totalPageNum.innerText = data.page_count;
    updateBill(data.page_count, data);
    return data;
  }

  function showCalculationError(error) {
    if (orderError) {
      orderError.innerText = error.message || 'Unable to calculate the price.';
      orderError.classList.remove('hidden');
    }
  }

  document.querySelectorAll('input[name="paper_size"], input[name="color_type"], input[name="print_side"], #gsm, #binding, #deliveryOption, #copies').forEach((control) => {
    control.addEventListener('change', () => {
      syncGsmOptions();
      if (control.id === 'binding' && calculatedOrder) {
        const bindingCost = currentBindingCost(calculatedOrder.page_count, calculatedOrder);
        updateBill(calculatedOrder.page_count, {
          ...calculatedOrder,
          binding_cost: bindingCost,
          grand_total: Number(calculatedOrder.print_cost) + bindingCost + Number(calculatedOrder.delivery_cost),
        });
      }
      if (uploadedFiles.length > 0) calculatePrice().catch(showCalculationError);
    });
  });
  syncGsmOptions();

  document.querySelectorAll('input[name="payment_method"]').forEach((control) => {
    control.addEventListener('change', () => {
      const isCod = selectedValue('payment_method') === 'cod';
      const trxInput = document.getElementById('trxId');
      const paymentHint = document.getElementById('paymentHint');
      if (trxInput) {
        trxInput.required = !isCod;
        trxInput.placeholder = isCod ? 'Not required for cash on delivery' : 'Required for digital payment';
      }
      if (paymentHint) paymentHint.innerText = isCod ? 'Cash on delivery is available for this order.' : 'Enter the TrxID so we can match your payment quickly.';
    });
  });

  function renderReview(data) {
    const summary = document.getElementById('reviewSummary');
    if (!summary) return;
    summary.innerHTML = `
      <div class="flex justify-between gap-4"><span>Files</span><strong>${data.file_count}</strong></div>
      <div class="flex justify-between gap-4"><span>Pages / sheets</span><strong>${data.page_count} / ${data.total_sheets}</strong></div>
      <div class="flex justify-between gap-4"><span>Copies</span><strong>${data.copies}</strong></div>
      <div class="flex justify-between gap-4"><span>Print</span><strong>৳ ${Number(data.print_cost).toFixed(2)}</strong></div>
      <div class="flex justify-between gap-4"><span>Binding + delivery</span><strong>৳ ${(Number(data.binding_cost) + Number(data.delivery_cost)).toFixed(2)}</strong></div>
      <div class="flex justify-between gap-4 border-t border-slate-200 pt-3 text-base text-navy"><span>Total</span><strong>৳ ${Number(data.grand_total).toFixed(2)}</strong></div>`;
  }

  const escapeReceiptHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[character]));
  function populatePrintableReceipt(orderId, data, customer) {
    const files = data.files || uploadedFiles.map((file) => ({ file_name: file.name, page_count: file.page_count || 0 }));
    document.getElementById('printReceiptOrderId').innerText = orderId;
    document.getElementById('printReceiptDate').innerText = new Date().toLocaleString();
    document.getElementById('printReceiptCustomer').innerText = customer;
    document.getElementById('printReceiptFiles').innerHTML = files.map((file) => `<span>${escapeReceiptHtml(file.file_name)} · ${file.page_count} pages</span>`).join('');
    document.getElementById('printReceiptBinding').innerText = document.getElementById('binding').selectedOptions[0].textContent;
    document.getElementById('printReceiptTrxId').innerText = document.getElementById('trxId').value || 'Cash on delivery';
    document.getElementById('printReceiptCosts').innerHTML = `
      <div class="flex justify-between gap-4"><span>Printing</span><strong>৳ ${Number(data.print_cost).toFixed(2)}</strong></div>
      <div class="flex justify-between gap-4"><span>Binding</span><strong>৳ ${Number(data.binding_cost).toFixed(2)}</strong></div>
      <div class="flex justify-between gap-4"><span>Delivery</span><strong>৳ ${Number(data.delivery_cost).toFixed(2)}</strong></div>`;
    document.getElementById('printReceiptTotal').innerText = `৳ ${Number(data.grand_total).toFixed(2)}`;
  }

  document.getElementById('printReceiptBtn')?.addEventListener('click', () => {
    if (calculatedOrder) {
      populatePrintableReceipt(calculatedOrder.order_id || document.getElementById('receiptOrderId').innerText, calculatedOrder, document.getElementById('customerName').value);
      window.print();
    }
  });

  // Step Navigation
  const steps = document.querySelectorAll('.step-panel');
  const progressSteps = document.querySelectorAll('.progress-step');

  window.goToStep = (stepNumber) => {
    steps.forEach(s => s.classList.add('hidden'));
    const target = document.querySelector(`.step-panel[data-panel="${stepNumber}"]`);
    if (target) target.classList.remove('hidden');

    progressSteps.forEach(p => {
      const pStep = parseInt(p.dataset.step);
      if (pStep <= stepNumber) {
        p.classList.add('bg-navy', 'text-white');
        p.classList.remove('bg-white', 'text-slate-400');
      } else {
        p.classList.remove('bg-navy', 'text-white');
        p.classList.add('bg-white', 'text-slate-400');
      }
    });

    const stepCounter = document.getElementById('stepCounter');
    if (stepCounter) stepCounter.innerText = `Step ${stepNumber} of 4`;
  };

  if (toStep2Btn) toStep2Btn.addEventListener('click', () => goToStep(2));
  
  document.querySelectorAll('.next-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const currentPanel = e.target.closest('.step-panel').dataset.panel;
      if (currentPanel === '2' || currentPanel === '3') {
        try {
          if (currentPanel === '2') await calculatePrice();
          if (currentPanel === '3') {
            if (!calculatedOrder) await calculatePrice();
            renderReview(calculatedOrder);
          }
        } catch (err) {
          if (orderError) {
            orderError.innerText = err.message;
            orderError.classList.remove('hidden');
          }
          return;
        }
      }
      goToStep(parseInt(currentPanel) + 1);
    });
  });

  document.querySelectorAll('.back-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const currentPanel = e.target.closest('.step-panel').dataset.panel;
      goToStep(parseInt(currentPanel) - 1);
    });
  });

  // Form Submission Logic
  if (orderForm) {
    orderForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (orderError) orderError.classList.add('hidden');

      if (uploadedFiles.length === 0) {
        if (orderError) {
          orderError.innerText = 'Please upload at least one PDF file.';
          orderError.classList.remove('hidden');
        }
        goToStep(1);
        return;
      }

      const submitBtn = document.getElementById('submitOrder');
      if (submitBtn) submitBtn.disabled = true;

      if (!calculatedOrder) {
        try {
          await calculatePrice();
        } catch (err) {
          if (orderError) {
            orderError.innerText = err.message;
            orderError.classList.remove('hidden');
          }
          if (submitBtn) submitBtn.disabled = false;
          return;
        }
      }
      const formData = new FormData();
      formData.append('session_id', calculatedOrder.session_id);
      formData.append('customer_name', document.getElementById('customerName').value);
      formData.append('customer_phone', document.getElementById('customerPhone').value);
      formData.append('address', document.getElementById('address').value);
      formData.append('area', document.getElementById('area').value);
      formData.append('delivery_option', document.getElementById('deliveryOption').value);
      formData.append('instructions', document.getElementById('instructions').value);
      formData.append('payment_method', selectedValue('payment_method'));
      formData.append('trx_id', document.getElementById('trxId').value);
      formData.append('payment_mobile', document.getElementById('paymentMobile').value);
      formData.append('amount', calculatedOrder.grand_total);

      try {
        const response = await fetch('/api/checkout', {
          method: 'POST',
          body: formData
        });

        if (!response.ok) {
          const errorText = await response.text();
          throw new Error(`Server error: ${response.status} ${response.statusText} - ${errorText}`);
        }

        const data = await response.json();

        if (response.ok && data.status === 'success') {
          orderForm.classList.add('hidden');
          const receipt = document.getElementById('receipt');
          if (receipt) {
            document.getElementById('receiptOrderId').innerText = data.order_id;
            document.getElementById('receiptMessage').innerText = data.message;
            calculatedOrder.order_id = data.order_id;
            populatePrintableReceipt(data.order_id, calculatedOrder, document.getElementById('customerName').value);
            receipt.classList.remove('hidden');
          }
        } else {
          throw new Error(data.detail || 'Failed to submit order');
        }
      } catch (err) {
        if (orderError) {
          orderError.innerText = err.message || 'Error submitting order. Please try again.';
          orderError.classList.remove('hidden');
        }
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  const trackForm = document.getElementById('trackForm');
  if (trackForm) {
    trackForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const result = document.getElementById('trackResult');
      try {
        const response = await fetch(`/api/orders/track/${encodeURIComponent(document.getElementById('trackId').value)}`);
        if (!response.ok) {
          const errorText = await response.text();
          throw new Error(`Server error: ${response.status} ${response.statusText} - ${errorText}`);
        }
        const data = await response.json();
        result.innerHTML = `<strong>${data.order_id}</strong><span class="ml-3">${data.status_label}</span><p class="mt-2 text-sm text-slate-500">${data.page_count} pages · ৳ ${Number(data.amount).toFixed(2)}</p>`;
        result.classList.remove('hidden');
      } catch (err) {
        result.innerText = err.message;
        result.classList.remove('hidden');
      }
    });
  }

  // Copy Payment Number Logic
  const copyNumBtn = document.getElementById('copyNumBtn');
  if (copyNumBtn) {
    copyNumBtn.addEventListener('click', () => {
      const numText = document.getElementById('paymentNum').innerText.trim();
      navigator.clipboard.writeText(numText).then(() => {
        const originalHTML = copyNumBtn.innerHTML;
        copyNumBtn.innerHTML = `<i data-lucide="check" class="w-3.5 h-3.5"></i> Copied!`;
        if (window.lucide) lucide.createIcons();
        setTimeout(() => {
          copyNumBtn.innerHTML = originalHTML;
          if (window.lucide) lucide.createIcons();
        }, 2000);
      }).catch(err => {
        console.error('Failed to copy text: ', err);
      });
    });
  }
  if (newOrderBtn) {
    newOrderBtn.addEventListener('click', () => {
      window.location.reload();
    });
  }

  const mobileMenuBtn = document.getElementById('menu-btn');
  const mobileMenu = document.getElementById('mobile-menu');
  if (mobileMenuBtn && mobileMenu) {
    mobileMenuBtn.addEventListener('click', () => {
      const isOpen = mobileMenu.classList.toggle('hidden') === false;
      mobileMenuBtn.setAttribute('aria-expanded', String(isOpen));
    });
    mobileMenu.querySelectorAll('a').forEach((link) => link.addEventListener('click', (event) => {
      const target = document.querySelector(link.getAttribute('href'));
      if (target) {
        event.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        window.history.replaceState(null, '', link.getAttribute('href'));
      }
      mobileMenu.classList.add('hidden');
      mobileMenuBtn.setAttribute('aria-expanded', 'false');
    }));
  }
});