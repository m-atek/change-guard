require_relative "../lib/shop/pricing"

RSpec.describe "format price" do
  it "formats a price" do
    Shop::Pricing.format_price(1250)
  end
end
