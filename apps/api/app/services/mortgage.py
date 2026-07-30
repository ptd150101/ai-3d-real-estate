from ..schemas import MortgageRequest, MortgageResponse
DISCLAIMER="Kết quả chỉ mang tính tham khảo. Lãi suất, phí và điều kiện thực tế do ngân hàng quyết định."
def calculate_mortgage(data:MortgageRequest)->MortgageResponse:
    principal=round(data.property_price*(1-data.down_payment_percent/100));months=data.term_years*12;monthly_rate=data.annual_interest_percent/100/12;preview=[]
    if data.repayment_method=="declining":
        principal_monthly=principal/months;balance=float(principal);total=0.0;first=0
        for month in range(1,months+1):
            interest=balance*monthly_rate;payment=principal_monthly+interest
            if month==1:first=round(payment)
            total+=payment
            if month<=12:preview.append({"month":month,"principal":round(principal_monthly),"interest":round(interest),"payment":round(payment),"balance":round(max(0,balance-principal_monthly))})
            balance-=principal_monthly
        monthly=first
    else:
        payment=principal/months if monthly_rate==0 else principal*monthly_rate*(1+monthly_rate)**months/((1+monthly_rate)**months-1);monthly=round(payment);first=None;balance=float(principal);total=payment*months
        for month in range(1,min(months,12)+1):
            interest=balance*monthly_rate;principal_part=payment-interest;balance-=principal_part;preview.append({"month":month,"principal":round(principal_part),"interest":round(interest),"payment":round(payment),"balance":round(max(0,balance))})
    return MortgageResponse(principal=principal,monthly_payment=monthly,first_month_payment=first,total_payment=round(total),total_interest=round(total-principal),disclaimer=DISCLAIMER,schedule_preview=preview)
