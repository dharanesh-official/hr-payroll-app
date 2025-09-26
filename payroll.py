import pandas as pd
from datetime import date
# We REMOVED the broken import: from .app import db, Holiday, LeaveRequest 

# MODIFIED: The function now accepts the database tools as arguments
def calculate_payslip(employee, year, month, db, Holiday, LeaveRequest):
    """
    Calculates the payslip for a given employee for a specific month and year.
    """
    # --- 1. Define the date range for the month ---
    start_of_month = date(year, month, 1)
    # pd.to_datetime helps create a timestamp, and .days_in_month gives us the last day
    end_of_month = date(year, month, pd.to_datetime(start_of_month).days_in_month)
    month_dates = pd.date_range(start_of_month, end_of_month)

    # --- 2. Get all public holidays for the month ---
    holidays_query = Holiday.query.filter(
        db.extract('year', Holiday.date) == year,
        db.extract('month', Holiday.date) == month
    ).all()
    public_holidays = [h.date for h in holidays_query]

    # --- 3. Determine the total number of payable days ---
    # Payable days are days that are NOT a Sunday and NOT a public holiday.
    payable_days_count = 0
    for day in month_dates:
        # day.weekday() returns 6 for Sunday
        if day.weekday() != 6 and day.date() not in public_holidays:
            payable_days_count += 1
            
    # Avoid division by zero if a month has no working days
    if payable_days_count == 0:
        return {
            "employee_name": employee.name,
            "month_year": start_of_month.strftime("%B %Y"),
            "gross_salary": employee.salary,
            "total_payable_days": 0,
            "per_day_salary": 0,
            "deductible_leave_days": 0,
            "deductions": 0,
            "net_salary": 0,
            "error": "No payable days in this month."
        }


    # --- 4. Calculate salary per day ---
    per_day_salary = employee.salary / payable_days_count

    # --- 5. Find approved, deductible leave days for the employee in this month ---
    approved_leaves_query = LeaveRequest.query.filter(
        LeaveRequest.user_id == employee.id,
        LeaveRequest.status == 'Approved'
    ).all()
    
    deductible_leave_days = 0
    for leave in approved_leaves_query:
        # Create a date range for each approved leave period
        leave_dates = pd.date_range(leave.start_date, leave.end_date)
        for leave_day in leave_dates:
            # Check if the leave day falls within the current payslip month
            if leave_day.month == month and leave_day.year == year:
                # Deduct pay only if the leave day was a payable day
                if leave_day.weekday() != 6 and leave_day.date() not in public_holidays:
                    deductible_leave_days += 1

    # --- 6. Calculate deductions and final salary ---
    deductions = deductible_leave_days * per_day_salary
    net_salary = employee.salary - deductions

    # --- 7. Return the payslip data as a dictionary ---
    payslip_data = {
        "employee_name": employee.name,
        "month_year": start_of_month.strftime("%B %Y"),
        "gross_salary": employee.salary,
        "total_payable_days": payable_days_count,
        "per_day_salary": per_day_salary,
        "deductible_leave_days": deductible_leave_days,
        "deductions": deductions,
        "net_salary": net_salary
    }
    
    return payslip_data